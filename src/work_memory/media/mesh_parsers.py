"""Fast, read-only, memory-bounded parsers for ``.3mf``, ``.stl``, and ``.obj`` meshes."""

from __future__ import annotations

import logging
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
MAX_TRIANGLES = 12_000
_MAX_TEXT_BYTES = 24 * 1024 * 1024
_MAX_3MF_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_3MF_TOTAL_BYTES = 256 * 1024 * 1024
_STL_DTYPE = np.dtype([("norm", "<f4", 3), ("verts", "<f4", (3, 3)), ("attr", "<u2")])


def _validate_3mf_limits(zf: zipfile.ZipFile) -> None:
    total = 0
    for info in zf.infolist():
        if info.file_size < 0 or info.file_size > _MAX_3MF_MEMBER_BYTES:
            raise ValueError(f"3MF member exceeds limit: {info.filename!r}")
        total += info.file_size
        if total > _MAX_3MF_TOTAL_BYTES:
            raise ValueError("3MF uncompressed archive exceeds limit.")


@dataclass(frozen=True, slots=True)
class MeshInfo:
    """Lightweight geometry summary displayed in MediaPreviewDialog."""

    vertex_count: int
    triangle_count: int
    label: str = ""


@dataclass(frozen=True, slots=True)
class ParsedMesh:
    """Bounded triangle array ``(N, 3, 3)`` plus summary metadata."""

    triangles: np.ndarray
    info: MeshInfo


def extract_3mf_thumbnail_bytes(path: Path) -> tuple[bytes, str] | None:
    """Read an embedded slicer preview PNG from a ``.3mf`` archive without modifying it."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            _validate_3mf_limits(zf)
            names = zf.namelist()
            lower_map = {n.lower(): n for n in names}
            for preferred in (
                "metadata/plate_1.png",
                "metadata/thumbnail.png",
                "auxiliaries/.thumbnails/thumbnail.png",
            ):
                if (hit := lower_map.get(preferred)) is not None:
                    return zf.read(hit), "3MF Plate Preview"
            for name in names:
                low = name.lower()
                if low.endswith(".png") and low.startswith(
                    ("metadata/", "auxiliaries/.thumbnails/")
                ):
                    return zf.read(name), "3MF Embedded Preview"
    except (OSError, PermissionError, ValueError, zipfile.BadZipFile) as exc:
        logger.debug("Unable to read 3MF thumbnail from %s: %s", path, exc)
    return None


def parse_3mf_model(path: Path) -> ParsedMesh | None:
    """Parse ``.model`` XML inside a ``.3mf`` archive into bounded triangles."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            _validate_3mf_limits(zf)
            model_name = next(
                (n for n in zf.namelist() if n.lower().endswith(".model")), None
            )
            if model_name is None:
                return None
            with zf.open(model_name, "r") as stream:
                root = ET.fromstring(stream.read(_MAX_TEXT_BYTES))
    except (OSError, PermissionError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        logger.debug("Unable to parse 3MF model %s: %s", path, exc)
        return None

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1].lower()
        if tag == "vertex":
            try:
                verts.append((float(elem.attrib["x"]), float(elem.attrib["y"]), float(elem.attrib["z"])))
            except (KeyError, ValueError):
                continue
        elif tag == "triangle":
            try:
                faces.append((int(elem.attrib["v1"]), int(elem.attrib["v2"]), int(elem.attrib["v3"])))
            except (KeyError, ValueError):
                continue
    return _build_indexed_mesh(verts, faces, label="3MF Mesh")


def parse_stl(path: Path) -> ParsedMesh | None:
    """Parse binary or ASCII ``.stl`` strictly read-only within ``MAX_TRIANGLES``."""
    try:
        size = path.stat().st_size
        if size < 84:
            return _parse_ascii_stl(path)
        with path.open("rb") as f:
            header = f.read(84)
            tri_count = struct.unpack("<I", header[80:84])[0]
            if tri_count > 0 and 84 + tri_count * 50 == size:
                return _read_binary_stl_chunks(f, tri_count)
    except (OSError, PermissionError, struct.error) as exc:
        logger.debug("Unable to parse STL %s: %s", path, exc)
        return None
    return _parse_ascii_stl(path)


def _read_binary_stl_chunks(handle: object, tri_count: int) -> ParsedMesh | None:
    stride = max(1, (tri_count + MAX_TRIANGLES - 1) // MAX_TRIANGLES)
    chunks: list[np.ndarray] = []
    chunk_tris = 8192
    read_so_far = 0
    while read_so_far < tri_count:
        batch = min(chunk_tris, tri_count - read_so_far)
        raw = handle.read(batch * 50)  # type: ignore[attr-defined]
        if len(raw) < 50:
            break
        usable = len(raw) // 50
        arr = np.frombuffer(raw[: usable * 50], dtype=_STL_DTYPE)["verts"]
        sampled = arr[::stride]
        if len(sampled):
            chunks.append(sampled.copy())
        read_so_far += usable
    if not chunks:
        return None
    tris = np.concatenate(chunks, axis=0)[:MAX_TRIANGLES].astype(np.float32, copy=False)
    return ParsedMesh(tris, MeshInfo(vertex_count=tri_count * 3, triangle_count=tri_count, label="STL"))


def _parse_ascii_stl(path: Path) -> ParsedMesh | None:
    tris_list: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = []
    cur: list[tuple[float, float, float]] = []
    bytes_read = 0
    try:
        with path.open("rb") as f:
            for raw_line in f:
                bytes_read += len(raw_line)
                if bytes_read > _MAX_TEXT_BYTES:
                    break
                line = raw_line.strip()
                if line.startswith(b"vertex "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            cur.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        except ValueError:
                            cur.clear()
                            continue
                        if len(cur) == 3:
                            tris_list.append((cur[0], cur[1], cur[2]))
                            cur.clear()
    except (OSError, PermissionError) as exc:
        logger.debug("Unable to read ASCII STL %s: %s", path, exc)
        return None
    if not tris_list:
        return None
    total = len(tris_list)
    stride = max(1, (total + MAX_TRIANGLES - 1) // MAX_TRIANGLES)
    arr = np.asarray(tris_list[::stride][:MAX_TRIANGLES], dtype=np.float32)
    return ParsedMesh(arr, MeshInfo(vertex_count=total * 3, triangle_count=total, label="STL"))


def parse_obj(path: Path) -> ParsedMesh | None:
    """Parse ``.obj`` vertices and faces strictly read-only within ``_MAX_TEXT_BYTES``."""
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    bytes_read = 0
    try:
        with path.open("rb") as f:
            for raw_line in f:
                bytes_read += len(raw_line)
                if bytes_read > _MAX_TEXT_BYTES:
                    break
                line = raw_line.strip()
                if line.startswith(b"v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        except ValueError:
                            continue
                elif line.startswith(b"f "):
                    tokens = line.split()[1:]
                    idx_list: list[int] = []
                    n_verts = len(verts)
                    for tok in tokens:
                        v_str = tok.split(b"/", 1)[0]
                        try:
                            idx = int(v_str)
                        except ValueError:
                            continue
                        resolved = (idx - 1) if idx > 0 else (n_verts + idx)
                        if 0 <= resolved < n_verts:
                            idx_list.append(resolved)
                    for i in range(1, len(idx_list) - 1):
                        faces.append((idx_list[0], idx_list[i], idx_list[i + 1]))
    except (OSError, PermissionError) as exc:
        logger.debug("Unable to parse OBJ %s: %s", path, exc)
        return None
    return _build_indexed_mesh(verts, faces, label="OBJ")


def _build_indexed_mesh(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    *,
    label: str,
) -> ParsedMesh | None:
    if not verts or not faces:
        return None
    total_tris = len(faces)
    stride = max(1, (total_tris + MAX_TRIANGLES - 1) // MAX_TRIANGLES)
    sampled_faces = np.asarray(faces[::stride][:MAX_TRIANGLES], dtype=np.int64)
    vert_arr = np.asarray(verts, dtype=np.float32)
    valid = (sampled_faces >= 0).all(axis=1) & (sampled_faces < len(vert_arr)).all(axis=1)
    sampled_faces = sampled_faces[valid]
    if len(sampled_faces) == 0:
        return None
    tris = vert_arr[sampled_faces]
    return ParsedMesh(tris, MeshInfo(vertex_count=len(verts), triangle_count=total_tris, label=label))
