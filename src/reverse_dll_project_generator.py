#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ========================================
# Author: Nikolay Dvurechensky
# Site: https://dvurechensky.pro/
# Gmail: dvurechenskysoft@gmail.com
# Last Updated: 20 августа 2026 09:35:15
# Version: 1.0.138
# ========================================
"""
reverse_dll_project_generator.py

Generates a VC++-friendly reverse/proxy DLL project from markdown exports.

Main fixes in this version:
- overload-aware internal names: GetCRC32_1_t / g_GetCRC32_1
- public C++ overloads remain normal human-readable overloads
- skips problematic CRT C exports like stricmp from wrapper generation
- better .def generation for stdcall using decorated byte count from parsed params
- generated code is closer to hand-written reverse proxy style
"""

import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


CRT_C_EXPORT_BLACKLIST = set()

CRT_FORWARD_EXPORTS = {
    "stricmp": "msvcrt._stricmp",
    "_stricmp": "msvcrt._stricmp",
    "strcmp": "msvcrt.strcmp",
    "_strcmp": "msvcrt.strcmp",
    "strncmp": "msvcrt.strncmp",
    "_strncmp": "msvcrt.strncmp",
    "strlen": "msvcrt.strlen",
    "_strlen": "msvcrt.strlen",
    "strcpy": "msvcrt.strcpy",
    "_strcpy": "msvcrt.strcpy",
    "strncpy": "msvcrt.strncpy",
    "_strncpy": "msvcrt.strncpy",
    "strcat": "msvcrt.strcat",
    "_strcat": "msvcrt.strcat",
    "strncat": "msvcrt.strncat",
    "_strncat": "msvcrt.strncat",
    "memcpy": "msvcrt.memcpy",
    "_memcpy": "msvcrt.memcpy",
    "memmove": "msvcrt.memmove",
    "_memmove": "msvcrt.memmove",
    "memset": "msvcrt.memset",
    "_memset": "msvcrt.memset",
    "memcmp": "msvcrt.memcmp",
    "_memcmp": "msvcrt.memcmp",
    "malloc": "msvcrt.malloc",
    "_malloc": "msvcrt.malloc",
    "free": "msvcrt.free",
    "_free": "msvcrt.free",
    "realloc": "msvcrt.realloc",
    "_realloc": "msvcrt.realloc",
    "atoi": "msvcrt.atoi",
    "_atoi": "msvcrt.atoi",
    "atol": "msvcrt.atol",
    "_atol": "msvcrt.atol",
    "qsort": "msvcrt.qsort",
    "_qsort": "msvcrt.qsort",
    "bsearch": "msvcrt.bsearch",
    "_bsearch": "msvcrt.bsearch",
}

CRT_SKIP_WRAPPER_EXPORTS = set(CRT_FORWARD_EXPORTS.keys())

CRT_DATA_LIKE_EXPORTS = {
    "FDUMP",
}

@dataclass
class Param:
    type: str
    name: str


@dataclass
class ExportEntry:
    address: str
    ordinal: int
    symbol: str
    undecorated: Optional[str] = None
    kind: str = "unknown"
    scope: Optional[str] = None
    file_stem: Optional[str] = None
    function_name: Optional[str] = None
    return_type: Optional[str] = None
    calling_convention: Optional[str] = None
    params: List[Param] = field(default_factory=list)
    is_data: bool = False
    signature_confidence: str = "low"
    overload_index: Optional[int] = None
    internal_base_name: Optional[str] = None
    typedef_name: Optional[str] = None
    global_name: Optional[str] = None
    skipped_reason: Optional[str] = None
    forward_target: Optional[str] = None

CPP_KEYWORDS = {
    "class", "struct", "union", "enum", "template", "typename", "namespace",
    "operator", "void", "char", "short", "int", "long", "float", "double",
    "signed", "unsigned", "bool", "const", "volatile", "__cdecl", "__stdcall",
    "__thiscall", "__fastcall", "return", "virtual", "public", "private",
    "protected", "static", "extern", "register", "mutable", "inline"
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def load_overrides(path: Optional[Path]) -> Dict[str, dict]:
    if not path:
        return {}
    if not path.exists():
        print(f"[WARN] overrides file not found: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        print(f"[WARN] failed to parse overrides: {path} -> {ex}")
        return {}

def sanitize_identifier(name: str) -> str:
    name = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not name:
        name = "unknown"
    if name[0].isdigit():
        name = "_" + name
    return name


def scope_to_file_stem(scope: str) -> str:
    return sanitize_identifier(scope.replace("::", "_")).lower()


def normalize_spaces(text: str) -> str:
    return " ".join(text.strip().split())


def normalize_type(t: str) -> str:
    t = normalize_spaces(t)
    replacements = [
        ("char const *", "const char*"),
        ("char const*", "const char*"),
        ("const char *", "const char*"),
        ("unsigned long *", "unsigned long*"),
        ("unsigned int *", "unsigned int*"),
        ("int *", "int*"),
        ("float *", "float*"),
        ("double *", "double*"),
        ("void *", "void*"),
        ("bool *", "bool*"),
        ("char *", "char*"),
        ("unsigned char *", "unsigned char*"),
        ("unsigned short *", "unsigned short*"),
        ("unsigned __int64 *", "unsigned __int64*"),
        (" *", "*"),
    ]
    for a, b in replacements:
        t = t.replace(a, b)
    t = t.replace(" & ", "&")
    return normalize_spaces(t)


def split_top_level_commas(s: str) -> List[str]:
    items = []
    depth_paren = 0
    depth_angle = 0
    depth_bracket = 0
    current = []

    for ch in s:
        if ch == '(':
            depth_paren += 1
        elif ch == ')':
            depth_paren -= 1
        elif ch == '<':
            depth_angle += 1
        elif ch == '>':
            depth_angle -= 1
        elif ch == '[':
            depth_bracket += 1
        elif ch == ']':
            depth_bracket -= 1

        if ch == ',' and depth_paren == 0 and depth_angle == 0 and depth_bracket == 0:
            items.append("".join(current).strip())
            current = []
            continue

        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        items.append(tail)

    return items


def extract_balanced_params(signature: str) -> Tuple[str, str]:
    end = signature.rfind(')')
    if end == -1:
        return signature.strip(), ""
    depth = 0
    start = -1
    for i in range(end, -1, -1):
        ch = signature[i]
        if ch == ')':
            depth += 1
        elif ch == '(':
            depth -= 1
            if depth == 0:
                start = i
                break
    if start == -1:
        return signature.strip(), ""
    head = signature[:start].strip()
    params = signature[start + 1:end].strip()
    return head, params


def parse_param(param_text: str, index: int) -> Param:
    p = normalize_type(param_text.strip())
    if not p:
        return Param("void*", f"param{index}")
    if p == "void":
        return Param("void", "")
    if "(*" in p or "(&" in p:
        return Param(p, f"param{index}")

    m = re.match(r'^(.*?)([A-Za-z_]\w*)$', p)
    if m:
        left = m.group(1).rstrip()
        right = m.group(2)
        if left:
            candidate_type = normalize_type(left)
            if right not in CPP_KEYWORDS and not candidate_type.endswith("::"):
                if candidate_type.endswith("*") or candidate_type.endswith("&") or " " in candidate_type:
                    return Param(candidate_type, right)

    return Param(p, f"param{index}")


def parse_signature(signature: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], List[Param]]:
    signature = normalize_spaces(signature)
    if not signature:
        return None, None, None, None, []

    head, params_text = extract_balanced_params(signature)
    if not head:
        return None, None, None, None, []

    scope = None
    function_name = None
    return_type = None
    calling_convention = None

    cc_match = re.search(r'\b(__cdecl|__stdcall|__thiscall|__fastcall)\b', head)
    if cc_match:
        calling_convention = cc_match.group(1)
        left = head[:cc_match.start()].strip()
        right = head[cc_match.end():].strip()
    else:
        left = ""
        right = head

    if "::" in right:
        scope, function_name = right.rsplit("::", 1)
        scope = scope.strip()
        function_name = function_name.strip()
    else:
        tokens = right.split()
        if tokens:
            function_name = tokens[-1]
            prefix = " ".join(tokens[:-1]).strip()
            if prefix and not left:
                left = prefix

    if left:
        return_type = normalize_type(left)

    params = []
    if params_text and params_text != "void":
        raw_params = split_top_level_commas(params_text)
        for i, rp in enumerate(raw_params, 1):
            p = parse_param(rp, i)
            if p.type != "void":
                params.append(p)

    return return_type, calling_convention, scope, function_name, params


def guess_data_export(symbol: str, undecorated: Optional[str]) -> bool:
    if undecorated:
        low = undecorated.lower()
        if " data" in low or low.startswith("data "):
            return True
    return symbol.isupper() and "(" not in symbol and "::" not in symbol and "?" not in symbol

def apply_override(entry: ExportEntry, override: dict) -> None:
    if not override:
        return

    if "kind" in override:
        entry.kind = override["kind"]

    if "scope" in override:
        entry.scope = override["scope"]

    if "file_stem" in override:
        entry.file_stem = override["file_stem"]

    if "function_name" in override:
        entry.function_name = override["function_name"]

    if "return_type" in override:
        entry.return_type = normalize_type(override["return_type"])

    if "calling_convention" in override:
        entry.calling_convention = override["calling_convention"]

    if "forward_target" in override:
        entry.forward_target = override["forward_target"]

    if "signature_confidence" in override:
        entry.signature_confidence = override["signature_confidence"]

    if "params" in override:
        entry.params = []
        for i, p in enumerate(override["params"], 1):
            p_type = normalize_type(p.get("type", "void*"))
            p_name = p.get("name", f"param{i}")
            entry.params.append(Param(p_type, p_name))

    if entry.kind == "cpp_scope_export" and entry.scope and not entry.file_stem:
        entry.file_stem = scope_to_file_stem(entry.scope)

    if entry.kind == "c_export":
        entry.file_stem = "exports_c"

    if entry.kind == "data_export":
        entry.is_data = True

def try_extract_scope_from_mangled(symbol: str) -> Optional[str]:
    m = re.match(r'^\?([^@]+)@(.+?)@@', symbol)
    if not m:
        return None
    raw_scope = m.group(2)
    parts = [p for p in raw_scope.split("@") if p]
    parts.reverse()
    return "::".join(parts) if parts else None


def try_extract_name_from_mangled(symbol: str) -> Optional[str]:
    m = re.match(r'^\?([^@]+)@', symbol)
    return m.group(1) if m else None


def escape_c_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def format_param_list(params: List[Param], include_names: bool = True) -> str:
    if not params:
        return "void"
    result = []
    for p in params:
        if include_names and p.name:
            result.append(f"{p.type} {p.name}".replace("* ", "*").replace("& ", "&"))
        else:
            result.append(p.type)
    return ", ".join(result)


def format_arg_list(params: List[Param]) -> str:
    return ", ".join(p.name for p in params if p.name)


def params_signature_key(params: List[Param]) -> str:
    if not params:
        return "void"
    return "|".join(normalize_type(p.type) for p in params)


def function_group_key(entry: ExportEntry) -> Tuple[str, str]:
    return ((entry.scope or ""), (entry.function_name or ""))


def signature_sort_key(entry: ExportEntry) -> Tuple[int, str, int]:
    return (len(entry.params), params_signature_key(entry.params), entry.ordinal)


def stdcall_param_size(param_type: str) -> int:
    t = normalize_type(param_type)
    if "*" in t or "&" in t:
        return 4
    if t in ("char", "unsigned char", "bool"):
        return 4
    if t in ("short", "unsigned short"):
        return 4
    if t in ("int", "unsigned int", "long", "unsigned long", "float"):
        return 4
    if t in ("double", "__int64", "unsigned __int64", "long long", "unsigned long long"):
        return 8
    return 4


def stdcall_bytes(params: List[Param]) -> int:
    total = 0
    for p in params:
        total += stdcall_param_size(p.type)
    return total


def make_internal_names(entries: List[ExportEntry]) -> None:
    groups: Dict[Tuple[str, str], List[ExportEntry]] = {}
    for e in entries:
        if e.kind in ("c_export", "cpp_scope_export"):
            groups.setdefault(function_group_key(e), []).append(e)

    for _, items in groups.items():
        items.sort(key=signature_sort_key)
        overloaded = len(items) > 1
        for i, e in enumerate(items, 1):
            e.overload_index = i if overloaded else None
            base = e.function_name or "UnknownFunction"
            e.internal_base_name = base if not overloaded else f"{base}_{i}"
            e.typedef_name = sanitize_identifier(f"{e.internal_base_name}_t")
            e.global_name = sanitize_identifier(f"g_{e.internal_base_name}")


EXPORT_BLOCK_RE = re.compile(
    r'^##\s+Address=([0-9A-Fa-f]+):::+Ordinal=(\d+)\s*$',
    re.MULTILINE
)


def classify_and_enrich_entry(entry: ExportEntry, overrides: Optional[Dict[str, dict]] = None) -> None:
    overrides = overrides or {}
    override = overrides.get(entry.symbol)

    # --------------------------------------------------
    # 1) Explicit forward CRT exports
    # --------------------------------------------------
    if entry.symbol in CRT_FORWARD_EXPORTS:
        entry.kind = "forward_export"
        entry.function_name = entry.symbol
        entry.forward_target = CRT_FORWARD_EXPORTS[entry.symbol]
        entry.return_type = None
        entry.calling_convention = None
        entry.params = []
        entry.signature_confidence = "manual"

        if override:
            apply_override(entry, override)
        return

    # --------------------------------------------------
    # 2) Known data exports
    # --------------------------------------------------
    if entry.symbol in CRT_DATA_LIKE_EXPORTS:
        entry.kind = "data_export"
        entry.function_name = entry.symbol
        entry.return_type = "void*"
        entry.calling_convention = None
        entry.params = []
        entry.is_data = True
        entry.signature_confidence = "manual"

        if override:
            apply_override(entry, override)
        return

    entry.is_data = guess_data_export(entry.symbol, entry.undecorated)

    if entry.is_data:
        entry.kind = "data_export"
        entry.function_name = entry.symbol
        entry.return_type = "void*"
        entry.signature_confidence = "medium"
        if override:
            apply_override(entry, override)
        return

    if entry.undecorated:
        ret_type, cc, scope, fn, params = parse_signature(entry.undecorated)
        entry.return_type = ret_type or "int"
        entry.calling_convention = cc or "__cdecl"
        entry.scope = scope
        entry.function_name = fn or entry.symbol
        entry.params = params
        entry.signature_confidence = "high"

        if scope:
            entry.kind = "cpp_scope_export"
            entry.file_stem = scope_to_file_stem(scope)
        else:
            entry.kind = "c_export"
            entry.file_stem = "exports_c"

        if override:
            apply_override(entry, override)
        return

    if entry.symbol.startswith("?") and "@@" in entry.symbol:
        scope = try_extract_scope_from_mangled(entry.symbol)
        fn = try_extract_name_from_mangled(entry.symbol)
        entry.scope = scope
        entry.function_name = fn or "UnknownFunction"
        entry.return_type = "int"
        entry.calling_convention = "__cdecl"
        entry.params = []
        entry.signature_confidence = "low"

        if scope:
            entry.kind = "cpp_scope_export"
            entry.file_stem = scope_to_file_stem(scope)
        else:
            entry.kind = "unknown"

        if override:
            apply_override(entry, override)
        return

    entry.function_name = entry.symbol
    entry.return_type = "int"
    entry.calling_convention = "__cdecl"
    entry.params = []
    entry.signature_confidence = "low"
    entry.kind = "c_export"
    entry.file_stem = "exports_c"

    if override:
        apply_override(entry, override)


def parse_exports_markdown(text: str, overrides: Optional[Dict[str, dict]] = None) -> List[ExportEntry]:
    entries: List[ExportEntry] = []
    matches = list(EXPORT_BLOCK_RE.finditer(text))
    overrides = overrides or {}

    for i, m in enumerate(matches):
        address = m.group(1).upper()
        ordinal = int(m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        symbol_match = re.search(r'^\s*Symbol=(.+?)\s*$', block, re.MULTILINE)
        undec_match = re.search(r'^\s*Symbol\s*\(undecorated\)=(.+?)\s*$', block, re.MULTILINE)

        if not symbol_match:
            continue

        symbol = symbol_match.group(1).strip()
        undecorated = undec_match.group(1).strip() if undec_match else None

        if not is_probably_valid_export_symbol(symbol):
            continue    

        entry = ExportEntry(
            address=address,
            ordinal=ordinal,
            symbol=symbol,
            undecorated=undecorated
        )

        classify_and_enrich_entry(entry, overrides=overrides)
        entries.append(entry)

    make_internal_names(entries)
    return entries

def parse_exports_raw_dump(text: str, overrides: Optional[Dict[str, dict]] = None) -> List[ExportEntry]:
    entries: List[ExportEntry] = []
    overrides = overrides or {}

    # Разбиваем на блоки по каждому "Address="
    blocks = re.split(r'(?=^\s*Address=)', text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        address_match = re.search(r'^\s*Address=(.+?)\s*$', block, re.MULTILINE)
        type_match = re.search(r'^\s*Type=(.+?)\s*$', block, re.MULTILINE)
        ordinal_match = re.search(r'^\s*Ordinal=(\d+)\s*$', block, re.MULTILINE)
        symbol_match = re.search(r'^\s*Symbol=(.+?)\s*$', block, re.MULTILINE)
        undec_match = re.search(r'^\s*Symbol\s*\(undecorated\)=(.+?)\s*$', block, re.MULTILINE)

        if not address_match or not ordinal_match or not symbol_match:
            continue

        export_type = type_match.group(1).strip() if type_match else None
        if export_type and export_type.lower() != "export":
            continue

        address = address_match.group(1).strip().upper()
        ordinal = int(ordinal_match.group(1))
        symbol = symbol_match.group(1).strip()
        undecorated = undec_match.group(1).strip() if undec_match else None

        if not is_probably_valid_export_symbol(symbol):
            continue    
        
        entry = ExportEntry(
            address=address,
            ordinal=ordinal,
            symbol=symbol,
            undecorated=undecorated
        )

        classify_and_enrich_entry(entry, overrides=overrides)
        entries.append(entry)

    make_internal_names(entries)
    return entries

def is_probably_valid_export_symbol(symbol: str) -> bool:
    if not symbol:
        return False

    symbol = symbol.strip()

    bad_prefixes = (
        "OptionalHeader.",
        "FileHeader.",
        "DOSHeader.",
        "NTHeaders.",
        "SectionHeader.",
        "IMAGE_",
    )

    if symbol.startswith(bad_prefixes):
        return False

    # Разрешаем:
    # - обычные C exports: DACOM_Acquire
    # - decorated C++ exports: ?GetCRC32@DACOM_CRC@@YAKPBD@Z
    # - data exports: FDUMP
    #
    # Запрещаем:
    # - всякие "foo.bar" псевдо-имена
    if "." in symbol and not symbol.startswith("?"):
        return False

    return True

def parse_exports(text: str, overrides: Optional[Dict[str, dict]] = None) -> List[ExportEntry]:
    overrides = overrides or {}

    # Сначала пытаемся markdown-формат
    entries = parse_exports_markdown(text, overrides=overrides)
    if entries:
        return entries

    # Если markdown не подошёл — пробуем raw dump
    entries = parse_exports_raw_dump(text, overrides=overrides)
    if entries:
        return entries

    return []

def build_header_guard(name: str) -> str:
    return sanitize_identifier(name.upper() + "_H")


def collect_scope_groups(entries: List[ExportEntry]) -> Dict[str, List[ExportEntry]]:
    groups: Dict[str, List[ExportEntry]] = {}
    for e in entries:
        if e.kind == "cpp_scope_export":
            groups.setdefault(e.file_stem or "unknown", []).append(e)
    return groups


def default_failure_return(ret_type: str) -> str:
    if ret_type == "void":
        return "return;"
    return f"return ({ret_type})0;"


def make_log_format_and_args(params: List[Param]) -> Tuple[str, List[str]]:
    if not params:
        return "", []

    parts = []
    args = []
    for p in params:
        t = normalize_type(p.type)
        parts.append(f"{p.name} = ")
        if t in ("float", "double"):
            parts[-1] += "%.2f"
            args.append(p.name)
        elif t in ("char", "unsigned char"):
            parts[-1] += "%c"
            args.append(p.name)
        elif t in ("const char*", "char*"):
            parts[-1] += "%s"
            args.append(f'{p.name} ? {p.name} : "<null>"')
        elif "*" in t or "&" in t:
            parts[-1] += "%p"
            args.append(p.name)
        else:
            parts[-1] += "%lu"
            args.append(p.name)

    return ", ".join(parts), args


def generate_globals_h(entries: List[ExportEntry]) -> str:
    lines: List[str] = []
    lines.append("#ifndef GLOBALS_H")
    lines.append("#define GLOBALS_H")
    lines.append("")
    lines.append("#include <windows.h>")
    lines.append("")
    lines.append("// typedefs")
    lines.append("")
    for e in entries:
        if e.kind not in ("c_export", "cpp_scope_export"):
            continue
        params = format_param_list(e.params, include_names=False)
        lines.append(f"typedef {e.return_type} ({e.calling_convention} *{e.typedef_name})({params});")
    lines.append("")
    lines.append("// globals")
    lines.append("")
    lines.append("extern HMODULE g_original;")
    lines.append("extern bool g_loadAttempted;")
    lines.append("")
    for e in entries:
        if e.kind not in ("c_export", "cpp_scope_export"):
            continue
        lines.append(f"extern {e.typedef_name} {e.global_name};")
    lines.append("")
    data_entries = [e for e in entries if e.kind == "data_export"]
    if data_entries:
        lines.append("// exported data")
        lines.append("")
        for e in data_entries:
            lines.append(f'extern "C" __declspec(dllexport) void* {e.function_name};')
        lines.append("")
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def generate_logging_h() -> str:
    return """#ifndef LOGGING_H
#define LOGGING_H

void LogMessage(const char* message);
void LogFormat(const char* fmt, ...);

#endif
"""


def generate_loader_h() -> str:
    return """#ifndef LOADER_H
#define LOADER_H

bool LoadOriginalDll();

#endif
"""


def generate_exports_c_h(entries: List[ExportEntry]) -> str:
    lines = ["#ifndef EXPORTS_C_H", "#define EXPORTS_C_H", ""]
    for e in entries:
        if e.kind != "c_export":
            continue
        params = format_param_list(e.params, include_names=True)
        lines.append(f'extern "C" {e.return_type} {e.calling_convention} {e.function_name}({params});')
    lines.append("")
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def generate_scope_h(scope: str, items: List[ExportEntry]) -> str:
    guard = build_header_guard(scope_to_file_stem(scope))
    lines = [f"#ifndef {guard}", f"#define {guard}", ""]
    ns_parts = scope.split("::")
    indent = ""
    for ns in ns_parts:
        lines.append(f"{indent}namespace {ns}")
        lines.append(f"{indent}{{")
        indent += "    "
    for e in items:
        params = format_param_list(e.params, include_names=True)
        lines.append(f"{indent}__declspec(dllexport) {e.return_type} {e.calling_convention} {e.function_name}({params});")
    for _ in ns_parts[::-1]:
        indent = indent[:-4]
        lines.append(f"{indent}}}")
    lines.append("")
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def generate_logging_cpp(log_file: str) -> str:
    return (
        '#include <stdio.h>\n'
        '#include <stdarg.h>\n'
        '#include "logging.h"\n'
        '\n'
        'void LogMessage(const char* message)\n'
        '{\n'
        f'    FILE* file = fopen("{escape_c_string(log_file)}", "a");\n'
        '    if (file)\n'
        '    {\n'
        '        fprintf(file, "%s\\n", message);\n'
        '        fclose(file);\n'
        '    }\n'
        '}\n'
        '\n'
        'void LogFormat(const char* fmt, ...)\n'
        '{\n'
        '    char buffer[1024];\n'
        '    va_list args;\n'
        '    va_start(args, fmt);\n'
        '#if defined(_MSC_VER)\n'
        '    _vsnprintf(buffer, sizeof(buffer) - 1, fmt, args);\n'
        "    buffer[sizeof(buffer) - 1] = '\\0';\n"
        '#else\n'
        '    vsnprintf(buffer, sizeof(buffer), fmt, args);\n'
        '#endif\n'
        '    va_end(args);\n'
        '    LogMessage(buffer);\n'
        '}\n'
    )


def generate_loader_cpp(entries: List[ExportEntry], original_dll: str) -> str:
    lines = [
        '#include <windows.h>',
        '#include "globals.h"',
        '#include "loader.h"',
        '#include "logging.h"',
        "",
        "HMODULE g_original = NULL;",
        "bool g_loadAttempted = false;",
        ""
    ]

    for e in entries:
        if e.kind in ("c_export", "cpp_scope_export"):
            lines.append(f"{e.typedef_name} {e.global_name} = NULL;")
    if any(e.kind == "data_export" for e in entries):
        lines.append("")
        for e in entries:
            if e.kind == "data_export":
                lines.append(f'extern "C" __declspec(dllexport) void* {e.function_name} = NULL;')

    lines.append("")
    lines.append("bool LoadOriginalDll()")
    lines.append("{")
    lines.append("    if (g_original != NULL)")
    lines.append("        return true;")
    lines.append("")
    lines.append("    if (g_loadAttempted)")
    lines.append("        return false;")
    lines.append("")
    lines.append("    g_loadAttempted = true;")
    lines.append("")
    lines.append(f'    g_original = LoadLibraryA("{escape_c_string(original_dll)}");')
    lines.append("    if (g_original == NULL)")
    lines.append("    {")
    lines.append(f'        LogMessage("Failed to load {escape_c_string(original_dll)}");')
    lines.append("        return false;")
    lines.append("    }")
    lines.append("")

    for e in entries:
        if e.kind == "data_export":
            lines.append(f'    {e.function_name} = (void*)GetProcAddress(g_original, "{escape_c_string(e.symbol)}");')
        elif e.kind in ("c_export", "cpp_scope_export"):
            lines.append(f'    {e.global_name} = ({e.typedef_name})GetProcAddress(g_original, "{escape_c_string(e.symbol)}");')

    lines.append("")
    for e in entries:
        if e.kind == "data_export":
            lines.append(f'    LogFormat("Resolve {e.function_name}: %p", {e.function_name});')
        elif e.kind in ("c_export", "cpp_scope_export"):
            lines.append(f'    LogFormat("Resolve {e.global_name}: %p", {e.global_name});')

    skipped = [e for e in entries if e.kind == "skipped_c_export"]
    if skipped:
        lines.append("")
        for e in skipped:
            lines.append(f'    LogMessage("Skipped export wrapper for {escape_c_string(e.function_name or e.symbol)} ({escape_c_string(e.skipped_reason or "skip")})");')

    lines.append("")
    lines.append("    return true;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def emit_unknown_signature_comment(lines: List[str], indent: str, e: ExportEntry) -> None:
    if e.signature_confidence == "high":
        return
    lines.append(f"{indent}// TODO: unresolved or fallback signature")
    lines.append(f"{indent}// Address: {e.address}")
    lines.append(f"{indent}// Original symbol: {e.symbol}")


def generate_exports_c_cpp(entries: List[ExportEntry]) -> str:
    lines = [
        '#include "globals.h"',
        '#include "loader.h"',
        '#include "logging.h"',
        '#include "exports_c.h"',
        ""
    ]

    for e in entries:
        if e.kind != "c_export":
            continue

        params_decl = format_param_list(e.params, include_names=True)
        call_args = format_arg_list(e.params)

        lines.append(f'extern "C" {e.return_type} {e.calling_convention} {e.function_name}({params_decl})')
        lines.append("{")
        emit_unknown_signature_comment(lines, "    ", e)

        fmt, args = make_log_format_and_args(e.params)
        if args:
            lines.append(f'    LogFormat("{e.function_name} called with parameters: {fmt}", {", ".join(args)});')
        else:
            lines.append(f'    LogFormat("{e.function_name} called");')

        lines.append(f"    if (!LoadOriginalDll() || !{e.global_name})")
        lines.append("    {")
        lines.append(f"        {default_failure_return(e.return_type)}")
        lines.append("    }")

        if e.return_type == "void":
            if call_args:
                lines.append(f"    {e.global_name}({call_args});")
            else:
                lines.append(f"    {e.global_name}();")
        else:
            if call_args:
                lines.append(f"    return {e.global_name}({call_args});")
            else:
                lines.append(f"    return {e.global_name}();")

        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def generate_scope_cpp(scope: str, items: List[ExportEntry]) -> str:
    header_name = f"{scope_to_file_stem(scope)}.h"
    lines = [
        '#include "globals.h"',
        '#include "loader.h"',
        '#include "logging.h"',
        f'#include "{header_name}"',
        ""
    ]

    ns_parts = scope.split("::")
    indent = ""
    for ns in ns_parts:
        lines.append(f"{indent}namespace {ns}")
        lines.append(f"{indent}{{")
        indent += "    "

    for e in items:
        params_decl = format_param_list(e.params, include_names=True)
        call_args = format_arg_list(e.params)

        lines.append(f"{indent}{e.return_type} {e.calling_convention} {e.function_name}({params_decl})")
        lines.append(f"{indent}{{")
        emit_unknown_signature_comment(lines, indent + "    ", e)

        fmt, args = make_log_format_and_args(e.params)
        if args:
            lines.append(f'{indent}    LogFormat("{e.function_name} called with parameters: {fmt}", {", ".join(args)});')
        else:
            lines.append(f'{indent}    LogFormat("{e.function_name} called");')

        lines.append(f"{indent}    if (!LoadOriginalDll() || !{e.global_name})")
        lines.append(f"{indent}    {{")
        lines.append(f"{indent}        {default_failure_return(e.return_type)}")
        lines.append(f"{indent}    }}")

        if e.return_type != "void" and e.function_name == "GetCRC32" and len(e.params) == 1 and normalize_type(e.params[0].type) == "const char*":
            lines.append(f"{indent}    unsigned long result = {e.global_name}({call_args});")
            lines.append(f'{indent}    LogFormat("GetCRC32 returned: %lu (0x%08lX)", result, result);')
            lines.append(f"{indent}    return result;")
        else:
            if e.return_type == "void":
                if call_args:
                    lines.append(f"{indent}    {e.global_name}({call_args});")
                else:
                    lines.append(f"{indent}    {e.global_name}();")
            else:
                if call_args:
                    lines.append(f"{indent}    return {e.global_name}({call_args});")
                else:
                    lines.append(f"{indent}    return {e.global_name}();")

        lines.append(f"{indent}}}")
        lines.append("")

    for _ in ns_parts[::-1]:
        indent = indent[:-4]
        lines.append(f"{indent}}}")

    return "\n".join(lines) + "\n"


def generate_main_cpp() -> str:
    return """#include <windows.h>

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID)
{
    if (fdwReason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(hinstDLL);

    return TRUE;
}
"""


def generate_def(entries: List[ExportEntry], dll_name: str) -> str:
    lines = [f"LIBRARY {dll_name}", "", "EXPORTS"]

    for e in sorted(entries, key=lambda x: x.ordinal):
        if e.kind == "data_export":
            lines.append(f"    {e.function_name} @{e.ordinal} DATA")

        elif e.kind == "forward_export":
            lines.append(f"    {e.function_name}={e.forward_target} @{e.ordinal}")

        elif e.kind == "c_export":
            if e.calling_convention == "__stdcall":
                lines.append(f"    {e.function_name}=_{e.function_name}@{stdcall_bytes(e.params)} @{e.ordinal}")
            else:
                lines.append(f"    {e.function_name} @{e.ordinal}")

        elif e.kind == "skipped_c_export":
            lines.append(f"    {e.symbol} @{e.ordinal}")

        elif e.kind == "cpp_scope_export":
            # intentionally omitted from DEF
            # these functions are implemented in code, but not exported via .def
            continue

    return "\n".join(lines) + "\n"


def generate_build_bat(entries: List[ExportEntry], dll_name: str) -> str:
    compile_lines = [
        r"cl /c /Iinclude src\_main.cpp            /Fobuild\_main.obj",
        r"cl /c /Iinclude src\logging.cpp          /Fobuild\logging.obj",
        r"cl /c /Iinclude src\loader.cpp           /Fobuild\loader.obj",
    ]

    if any(e.kind == "c_export" for e in entries):
        compile_lines.append(r"cl /c /Iinclude src\exports_c.cpp        /Fobuild\exports_c.obj")

    groups = collect_scope_groups(entries)
    for stem in sorted(groups):
        compile_lines.append(rf"cl /c /Iinclude src\{stem}.cpp            /Fobuild\{stem}.obj")

    link_objs = [
        r" build\_main.obj ^",
        r" build\logging.obj ^",
        r" build\loader.obj ^",
    ]
    if any(e.kind == "c_export" for e in entries):
        link_objs.append(r" build\exports_c.obj ^")
    for stem in sorted(groups):
        link_objs.append(rf" build\{stem}.obj ^")

    lines = [
        "@echo off",
        "setlocal",
        "",
        "echo =========================",
        f"echo Building {dll_name}.dll...",
        "echo =========================",
        "",
        "if not exist build mkdir build",
        "",
    ]
    lines.extend(compile_lines)
    lines.extend([
        "",
        "link /DLL ^",
    ])
    lines.extend(link_objs)
    lines.extend([
        rf" /DEF:src\{dll_name}.def ^",
        rf" /OUT:build\{dll_name}.dll ^",
        " user32.lib ^",
        " /BASE:0x065B0000",
        "",
        "echo.",
        "echo DONE",
        rf"echo Output: build\{dll_name}.dll",
        "pause",
        ""
    ])
    return "\n".join(lines)


def generate_manifest(entries: List[ExportEntry], dll_name: str, original_dll: str) -> str:
    data = {
        "dll_name": dll_name,
        "original_dll": original_dll,
        "exports": [
            {
                "address": e.address,
                "ordinal": e.ordinal,
                "symbol": e.symbol,
                "undecorated": e.undecorated,
                "kind": e.kind,
                "scope": e.scope,
                "file": e.file_stem,
                "function_name": e.function_name,
                "return_type": e.return_type,
                "calling_convention": e.calling_convention,
                "params": [asdict(p) for p in e.params],
                "is_data": e.is_data,
                "signature_confidence": e.signature_confidence,
                "overload_index": e.overload_index,
                "internal_base_name": e.internal_base_name,
                "typedef_name": e.typedef_name,
                "global_name": e.global_name,
                "skipped_reason": e.skipped_reason,
                "forward_target": e.forward_target,
            }
            for e in sorted(entries, key=lambda x: x.ordinal)
        ]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def generate_project(entries: List[ExportEntry], out_dir: Path, dll_name: str, original_dll: str, log_file: str) -> None:
    include_dir = out_dir / "include"
    src_dir = out_dir / "src"
    ensure_dir(include_dir)
    ensure_dir(src_dir)

    write_text(include_dir / "globals.h", generate_globals_h(entries))
    write_text(include_dir / "logging.h", generate_logging_h())
    write_text(include_dir / "loader.h", generate_loader_h())

    if any(e.kind == "c_export" for e in entries):
        write_text(include_dir / "exports_c.h", generate_exports_c_h(entries))

    scope_groups = collect_scope_groups(entries)
    scope_name_by_stem: Dict[str, str] = {}
    for e in entries:
        if e.kind == "cpp_scope_export" and e.scope:
            scope_name_by_stem[e.file_stem or scope_to_file_stem(e.scope)] = e.scope

    for stem, items in scope_groups.items():
        write_text(include_dir / f"{stem}.h", generate_scope_h(scope_name_by_stem[stem], items))

    write_text(src_dir / "_main.cpp", generate_main_cpp())
    write_text(src_dir / "logging.cpp", generate_logging_cpp(log_file))
    write_text(src_dir / "loader.cpp", generate_loader_cpp(entries, original_dll))

    if any(e.kind == "c_export" for e in entries):
        write_text(src_dir / "exports_c.cpp", generate_exports_c_cpp(entries))

    for stem, items in scope_groups.items():
        write_text(src_dir / f"{stem}.cpp", generate_scope_cpp(scope_name_by_stem[stem], items))

    write_text(src_dir / f"{dll_name}.def", generate_def(entries, dll_name))
    write_text(out_dir / "build.bat", generate_build_bat(entries, dll_name))
    write_text(out_dir / "manifest.json", generate_manifest(entries, dll_name, original_dll))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reverse DLL proxy project from exports markdown.")
    parser.add_argument("exports_md", help="Path to exports markdown file")
    parser.add_argument("-o", "--out", default="generated_proxy", help="Output directory")
    parser.add_argument("--dll-name", default="dacom", help="Generated DLL name without extension")
    parser.add_argument("--original-dll", default="dacom_addon.dll", help="Original DLL to load at runtime")
    parser.add_argument("--log-file", default="dvurechensky_dacom.ini", help="Runtime log file name")
    parser.add_argument("--overrides", default=None, help="Path to overrides.json")
    args = parser.parse_args()

    exports_path = Path(args.exports_md)
    if not exports_path.exists():
        raise SystemExit(f"Input file not found: {exports_path}")

    text = exports_path.read_text(encoding="utf-8")
    overrides = load_overrides(Path(args.overrides)) if args.overrides else {}
    entries = parse_exports(text, overrides=overrides)
    if not entries:
        raise SystemExit("No export entries parsed from input.")

    generate_project(
        entries=entries,
        out_dir=Path(args.out),
        dll_name=args.dll_name,
        original_dll=args.original_dll,
        log_file=args.log_file,
    )

    print(f"Generated project: {args.out}")
    print(f"Exports parsed: {len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
