"""Lector/escritor de `global-metadata.dat` (IL2CPP v31) que permite ALARGAR literales.

El parche de la URL solo necesitaba sustituir en sitio (misma longitud). Traducir a otro
idioma necesita strings más largos, y ahí el blob de literales crece: este módulo lo hace
añadiendo los textos nuevos al final del blob y desplazando todas las secciones posteriores,
corrigiendo los offsets de la cabecera. En IL2CPP todas las referencias internas son
relativas a su sección, así que un desplazamiento uniforme es seguro.

Cabecera (256 bytes = 2 campos fijos + 31 pares offset/tamaño):

    u32 sanity (0xFAB11BAF) · i32 version · luego pares (offset, size)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SANITY = 0xFAB11BAF
HEADER_SIZE = 256

# orden exacto de los 31 pares de la cabecera (v29/v31)
SECTIONS = [
    "stringLiteral", "stringLiteralData", "strings", "events", "properties", "methods",
    "parameterDefaultValues", "fieldDefaultValues", "fieldAndParameterDefaultValueData",
    "fieldMarshaledSizes", "parameters", "fields", "genericParameters",
    "genericParameterConstraints", "genericContainers", "nestedTypes", "interfaces",
    "vtableMethods", "interfaceOffsets", "typeDefinitions", "images", "assemblies",
    "fieldRefs", "referencedAssemblies", "attributeData", "attributeDataRange",
    "unresolvedVirtualCallParameterTypes", "unresolvedVirtualCallParameterRanges",
    "windowsRuntimeTypeNames", "windowsRuntimeStrings", "exportedTypeDefinitions",
]


@dataclass(slots=True)
class Literal:
    index: int
    length: int
    data_index: int
    text: str


class Metadata:
    def __init__(self, blob: bytes):
        self.blob = bytearray(blob)
        sanity, self.version = struct.unpack_from("<Ii", self.blob, 0)
        if sanity != SANITY:
            raise ValueError(f"cabecera IL2CPP inválida (sanity={sanity:#x})")
        self.pairs: dict[str, tuple[int, int]] = {}
        for i, name in enumerate(SECTIONS):
            off, size = struct.unpack_from("<II", self.blob, 8 + i * 8)
            self.pairs[name] = (off, size)

    # ------------------------------------------------------------------ lectura
    @property
    def literal_table(self) -> tuple[int, int]:
        return self.pairs["stringLiteral"]

    @property
    def literal_data(self) -> tuple[int, int]:
        return self.pairs["stringLiteralData"]

    def literals(self) -> list[Literal]:
        table_off, table_count = self.literal_table
        data_off, _ = self.literal_data
        out = []
        for i in range(table_count):
            length, data_index = struct.unpack_from("<II", self.blob, table_off + i * 8)
            raw = bytes(self.blob[data_off + data_index:data_off + data_index + length])
            out.append(Literal(i, length, data_index, raw.decode("utf-8", "replace")))
        return out

    def literal_map(self) -> dict[str, list[int]]:
        """texto -> índices (puede haber literales repetidos)."""
        out: dict[str, list[int]] = {}
        for lit in self.literals():
            out.setdefault(lit.text, []).append(lit.index)
        return out

    # ----------------------------------------------------------------- escritura
    def set_literal(self, index: int, text: str) -> None:
        """Sustituye un literal por otro de CUALQUIER longitud.

        - Si cabe en el hueco actual: se escribe en sitio (con relleno nulo).
        - Si no: se añade al final del blob de literales y se desplaza lo que venga después.
        """
        table_off, _ = self.literal_table
        data_off, data_size = self.literal_data
        length, data_index = struct.unpack_from("<II", self.blob, table_off + index * 8)
        new = text.encode("utf-8")

        if len(new) <= length:
            start = data_off + data_index
            self.blob[start:start + length] = new + b"\x00" * (length - len(new))
            struct.pack_into("<I", self.blob, table_off + index * 8, len(new))
            return

        appended = len(new) - 0
        # 1) el nuevo texto va al final del blob de literales
        new_index = data_size
        insert_at = data_off + data_size
        self.blob[insert_at:insert_at] = new
        self._shift_after(insert_at, appended)
        # 2) la tabla de literales está ANTES del blob: no se desplaza
        struct.pack_into("<I", self.blob, table_off + index * 8, len(new))
        struct.pack_into("<I", self.blob, table_off + index * 8 + 4, new_index)
        # 3) el blob crece
        off, size = self.pairs["stringLiteralData"]
        self.pairs["stringLiteralData"] = (off, size + appended)
        self._write_header()

    def _shift_after(self, position: int, delta: int) -> None:
        """Desplaza las secciones que empiezan en/después de `position` y corrige la cabecera."""
        for name, (off, size) in list(self.pairs.items()):
            if off >= position:
                self.pairs[name] = (off + delta, size)

    def _write_header(self) -> None:
        for i, name in enumerate(SECTIONS):
            off, size = self.pairs[name]
            struct.pack_into("<II", self.blob, 8 + i * 8, off, size)

    def to_bytes(self) -> bytes:
        self._write_header()
        return bytes(self.blob)


def load(path: str) -> Metadata:
    with open(path, "rb") as fh:
        return Metadata(fh.read())


def apply_translations(blob: bytes, translations: dict[str, str]) -> tuple[bytes, int]:
    """Aplica {texto_original: texto_nuevo}. Devuelve (blob, nº de literales cambiados)."""
    md = Metadata(blob)
    index = md.literal_map()
    changed = 0
    for source, target in translations.items():
        if not target or target == source:
            continue
        for i in index.get(source, []):
            md.set_literal(i, target)
            changed += 1
    return md.to_bytes(), changed
