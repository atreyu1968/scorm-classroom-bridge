from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
import zipfile
import shutil
import uuid


@dataclass
class ManifestInfo:
    title: str
    version: str
    entrypoint: str
    metadata: dict


def _local(tag: str) -> str:
    return tag.split('}', 1)[-1]


def _first_child_by_local(root, name):
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def _children_by_local(root, name):
    return [el for el in root.iter() if _local(el.tag) == name]


def parse_manifest(xml_path: Path) -> ManifestInfo:
    root = ET.parse(xml_path).getroot()
    organizations = _first_child_by_local(root, 'organizations')
    resources = _first_child_by_local(root, 'resources')
    if resources is None:
        raise ValueError('El imsmanifest.xml no contiene <resources>.')

    title = 'SCORM sin título'
    item_ref = None
    if organizations is not None:
        default_org = organizations.attrib.get('default')
        orgs = [x for x in list(organizations) if _local(x.tag) == 'organization']
        chosen = next((x for x in orgs if x.attrib.get('identifier') == default_org), orgs[0] if orgs else None)
        if chosen is not None:
            t = next((x for x in list(chosen) if _local(x.tag) == 'title'), None)
            if t is not None and (t.text or '').strip():
                title = (t.text or '').strip()
            first_item = next((x for x in chosen.iter() if _local(x.tag) == 'item' and x.attrib.get('identifierref')), None)
            if first_item is not None:
                item_ref = first_item.attrib.get('identifierref')

    resource_nodes = [x for x in list(resources) if _local(x.tag) == 'resource']
    selected = next((x for x in resource_nodes if x.attrib.get('identifier') == item_ref), None)
    if selected is None and resource_nodes:
        selected = resource_nodes[0]
    if selected is None:
        raise ValueError('No se encontró ningún recurso ejecutable en el manifiesto.')

    href = selected.attrib.get('href')
    if not href:
        file_node = next((x for x in selected.iter() if _local(x.tag) == 'file' and x.attrib.get('href')), None)
        href = file_node.attrib.get('href') if file_node is not None else None
    if not href:
        raise ValueError('El recurso principal del SCORM no tiene atributo href.')

    schema = _first_child_by_local(root, 'schema')
    schemaversion = _first_child_by_local(root, 'schemaversion')
    version_text = ((schemaversion.text if schemaversion is not None else '') or '').strip()
    schema_text = ((schema.text if schema is not None else '') or '').strip()
    low = f'{schema_text} {version_text}'.lower()
    version = '2004' if '2004' in low or '1.3' in low else '1.2'

    return ManifestInfo(
        title=title,
        version=version,
        entrypoint=str(PurePosixPath(href)),
        metadata={
            'schema': schema_text,
            'schemaversion': version_text,
            'resource_identifier': selected.attrib.get('identifier'),
            'resource_type': selected.attrib.get('type'),
            'scorm_type': next((v for k, v in selected.attrib.items() if k.endswith('scormType')), None),
        },
    )


def _safe_extract(zip_file: zipfile.ZipFile, target: Path):
    target = target.resolve()
    for member in zip_file.infolist():
        member_path = target / member.filename
        resolved = member_path.resolve()
        if target != resolved and target not in resolved.parents:
            raise ValueError(f'Ruta no segura dentro del ZIP: {member.filename}')
    zip_file.extractall(target)


def import_scorm_zip(zip_path: Path, upload_root: Path) -> tuple[str, ManifestInfo]:
    folder_name = str(uuid.uuid4())
    target = upload_root / folder_name
    target.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            _safe_extract(zf, target)
        manifests = list(target.rglob('imsmanifest.xml'))
        if not manifests:
            raise ValueError('El ZIP no contiene imsmanifest.xml.')
        manifest_path = min(manifests, key=lambda p: len(p.parts))
        info = parse_manifest(manifest_path)
        manifest_dir = manifest_path.parent
        # Normalize the package so the manifest directory becomes the serving root.
        if manifest_dir != target:
            normalized = upload_root / f'{folder_name}-normalized'
            shutil.move(str(manifest_dir), str(normalized))
            shutil.rmtree(target, ignore_errors=True)
            normalized.rename(target)
        entry = (target / info.entrypoint).resolve()
        if not entry.exists() or target.resolve() not in entry.parents:
            raise ValueError(f'El recurso inicial no existe: {info.entrypoint}')
        return folder_name, info
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
