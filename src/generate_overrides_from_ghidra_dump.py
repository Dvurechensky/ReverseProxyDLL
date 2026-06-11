#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ========================================
# Author: Nikolay Dvurechensky
# Site: https://dvurechensky.pro/
# Gmail: dvurechenskysoft@gmail.com
# Last Updated: 11 июня 2026 13:24:45
# Version: 1.0.67
# ========================================
import re
import sys
import json
from pathlib import Path

CALLING_CONVENTIONS = [
    "__cdecl",
    "__stdcall",
    "__fastcall",
    "__thiscall",
    "__vectorcall",
]

SKIP_NAMES = {
    "__SEH_prolog",
    "__SEH_epilog",
    "_except_handler3",
    "_except_handler4_common",
    "__RTC_CheckEsp",
    "__security_check_cookie",
    "__report_gsfailure",
}

BAD_PREFIXES = (
    "if ",
    "while ",
    "for ",
    "switch ",
    "return ",
    "goto ",
    "case ",
)

STRING_FUNCS = (
    "strcmp", "strncmp", "stricmp", "_stricmp", "strlen",
    "strcpy", "strncpy", "strcat", "strncat",
    "lstrcmp", "lstrcmpi", "wsprintf", "sprintf",
)

MEMORY_FUNCS = (
    "memcpy", "memmove", "memset", "memcmp",
)

WINAPI_STRING_HINTS = (
    "CreateFileA", "CreateFileW",
    "LoadLibraryA", "LoadLibraryW",
    "GetModuleHandleA", "GetModuleHandleW",
    "GetProcAddress",
)

TYPE_ALIASES = {
    "undefined": "void",
    "undefined1": "unsigned char",
    "undefined2": "unsigned short",
    "undefined4": "unsigned int",
    "undefined8": "unsigned long long",
    "byte": "unsigned char",
    "uchar": "unsigned char",
    "ushort": "unsigned short",
    "uint": "unsigned int",
    "ulong": "unsigned long",
}

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

# TYPE NORMALIZATION

def normalize_type(t: str) -> str:
    if not t:
        return "void"

    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    t = t.replace(" *", "*")
    t = t.replace("* ", "*")

    # replace bare aliases only
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]

    # replace alias inside pointer forms
    for src, dst in TYPE_ALIASES.items():
        t = re.sub(rf"\b{re.escape(src)}\b", dst, t)

    return t


def is_unknownish_type(t: str) -> bool:
    t = normalize_type(t)
    unknown_markers = (
        "unsigned int",
        "unsigned long long",
        "void",
    )
    # deliberately conservative: only "unknownish" if it came from undefined*
    return True if t in unknown_markers else False


def pointerize(base_type: str) -> str:
    base_type = normalize_type(base_type)
    if base_type.endswith("*"):
        return base_type
    return f"{base_type}*"


# PARAM PARSER

def split_params(params_raw: str):
    params_raw = params_raw.strip()
    if params_raw == "" or params_raw == "void":
        return []

    result = []
    current = []
    depth = 0

    for ch in params_raw:
        if ch == ',' and depth == 0:
            result.append("".join(current).strip())
            current = []
            continue

        current.append(ch)

        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1

    if current:
        result.append("".join(current).strip())

    return result


def parse_param(param: str, index: int):
    param = param.strip()

    if "(*" in param or "(__cdecl*" in param or "(__stdcall*" in param:
        return {
            "type": normalize_type(param),
            "name": f"param_{index}",
            "original_type": param,
            "type_confidence": "high",
            "inference_reason": "function pointer syntax in signature"
        }

    m = re.match(r"^(.*?)([A-Za-z_][A-Za-z0-9_]*)$", param)
    if m:
        type_part = m.group(1).strip()
        name_part = m.group(2).strip()

        if not type_part:
            return {
                "type": "void*",
                "name": name_part,
                "original_type": "",
                "type_confidence": "low",
                "inference_reason": "missing type in signature"
            }

        norm = normalize_type(type_part)
        return {
            "type": norm,
            "name": name_part,
            "original_type": type_part,
            "type_confidence": "high" if "undefined" not in type_part else "low",
            "inference_reason": "taken from decompiler signature"
        }

    norm = normalize_type(param)
    return {
        "type": norm,
        "name": f"param_{index}",
        "original_type": param,
        "type_confidence": "high" if "undefined" not in param else "low",
        "inference_reason": "fallback parse from decompiler signature"
    }


# KIND DETECTION

def detect_kind(function_name: str):
    if function_name.startswith("?"):
        return "cpp_export"
    if function_name.startswith("FUN_") or function_name.startswith("sub_"):
        return "internal"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", function_name):
        return "c_export"
    return "internal"


def is_forward_export_name(function_name: str) -> bool:
    return function_name in CRT_FORWARD_EXPORTS


def make_forward_export_override(function_name: str) -> dict:
    return {
        "kind": "forward_export",
        "function_name": function_name,
        "forward_target": CRT_FORWARD_EXPORTS[function_name],
        "signature_confidence": "manual"
    }

# HEADER DETECTION

def looks_like_function_header_start(line: str) -> bool:
    line = line.strip()

    if not line:
        return False

    if line.startswith("//") or line.startswith("/*") or line.startswith("*") or line.startswith(";"):
        return False

    if line.startswith(BAD_PREFIXES):
        return False

    if "=" in line and "(" in line and ")" in line:
        return False

    if line.startswith("(*"):
        return False

    if "(" in line and ")" in line and "{" not in line and ";" not in line:
        return True

    if any(cc in line for cc in CALLING_CONVENTIONS):
        return True

    return False


# EXTRACT FUNCTIONS (HEADER + BODY)

def extract_functions(text: str):
    lines = text.splitlines()
    results = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not looks_like_function_header_start(line):
            i += 1
            continue

        collected = [line]
        j = i + 1
        joined = " ".join(collected)

        while j < len(lines):
            if ")" in joined:
                break

            nxt = lines[j].strip()

            if nxt == "{" or nxt.startswith("{"):
                break

            if nxt.startswith(BAD_PREFIXES) or "=" in nxt or nxt.startswith("(*"):
                break

            if nxt:
                collected.append(nxt)
                joined = " ".join(collected)

            j += 1

        joined = re.sub(r"\s+", " ", " ".join(collected)).strip()

        if not re.match(r"^.+?\s+[^\s(]+\s*\(.*\)$", joined):
            i = j if j > i else i + 1
            continue

        # move to body
        while j < len(lines) and lines[j].strip() == "":
            j += 1

        if j >= len(lines) or not lines[j].strip().startswith("{"):
            results.append({"signature": joined, "body": ""})
            i = j if j > i else i + 1
            continue

        brace_depth = 0
        body_lines = []
        started = False

        while j < len(lines):
            raw = lines[j]
            stripped = raw.strip()

            if "{" in raw:
                brace_depth += raw.count("{")
                started = True

            if started:
                body_lines.append(raw)

            if "}" in raw:
                brace_depth -= raw.count("}")
                if started and brace_depth <= 0:
                    j += 1
                    break

            j += 1

        results.append({
            "signature": joined,
            "body": "\n".join(body_lines)
        })

        i = j if j > i else i + 1

    return results


# SIGNATURE PARSER

def parse_signature(sig: str):
    sig = sig.strip().rstrip(";")

    m = re.match(r"^(.*?)\s+([^\s(]+)\((.*)\)$", sig)
    if not m:
        return None

    left = m.group(1).strip()
    function_name = m.group(2).strip()
    params_raw = m.group(3).strip()

    if function_name in SKIP_NAMES:
        return None

    if function_name in {"if", "while", "for", "switch", "return"}:
        return None

    # -------------------------------------------------
    # CRT / runtime exports that must be DEF forwards,
    # not generated wrapper functions
    # -------------------------------------------------
    if is_forward_export_name(function_name):
        return make_forward_export_override(function_name)

    calling_convention = "__cdecl"
    for cc in CALLING_CONVENTIONS:
        if re.search(rf"\b{re.escape(cc)}\b", left):
            calling_convention = cc
            left = re.sub(rf"\b{re.escape(cc)}\b", "", left).strip()
            break

    return_type = normalize_type(left)

    params = [parse_param(p, i) for i, p in enumerate(split_params(params_raw), start=1)]
    kind = detect_kind(function_name)

    return {
        "kind": kind,
        "function_name": function_name,
        "return_type": return_type,
        "original_return_type": left,
        "calling_convention": calling_convention,
        "params": params,
        "signature_confidence": "ghidra"
    }


# BODY ANALYSIS

def find_param_usage(body: str, param_name: str):
    escaped = re.escape(param_name)

    return {
        "assigned_through_pointer": bool(re.search(rf"\*\s*{escaped}\s*=", body)),
        "dereferenced": bool(re.search(rf"\*\s*{escaped}\b", body)),
        "indexed": bool(re.search(rf"\b{escaped}\s*\[", body)),
        "addr_arith": bool(re.search(rf"\b{escaped}\s*(\+|-)", body)),
        "null_checked": bool(re.search(rf"\b{escaped}\s*==\s*0|\b{escaped}\s*!=\s*0|0\s*==\s*\b{escaped}|0\s*!=\s*\b{escaped}", body)),
        "used_in_string_func": bool(re.search(rf"\b(?:{'|'.join(map(re.escape, STRING_FUNCS))})\s*\([^)]*\b{escaped}\b", body)),
        "used_in_memory_func": bool(re.search(rf"\b(?:{'|'.join(map(re.escape, MEMORY_FUNCS))})\s*\([^)]*\b{escaped}\b", body)),
        "used_in_winapi_string_hint": bool(re.search(rf"\b(?:{'|'.join(map(re.escape, WINAPI_STRING_HINTS))})\s*\([^)]*\b{escaped}\b", body)),
        "cast_to_char_ptr": bool(re.search(rf"\((?:const\s+)?char\s*\*\)\s*{escaped}", body)),
        "cast_to_void_ptr": bool(re.search(rf"\(void\s*\*\)\s*{escaped}", body)),
        "passed_by_value": bool(re.search(rf"\([^)]*\b{escaped}\b[^)]*\)", body)),
    }


def infer_better_param_type(param: dict, body: str):
    name = param["name"]
    current_type = normalize_type(param["type"])
    usage = find_param_usage(body, name)

    reasons = []
    score_high = 0
    score_medium = 0

    # already explicit strong type, keep it unless body clearly says pointer
    explicit_unknown = (
        "undefined" in param.get("original_type", "") or
        current_type in ("unsigned int", "unsigned long long", "void")
    )

    inferred_type = current_type
    confidence = param.get("type_confidence", "low")

    if usage["assigned_through_pointer"] or usage["indexed"] or usage["addr_arith"]:
        if usage["used_in_string_func"] or usage["cast_to_char_ptr"] or usage["used_in_winapi_string_hint"]:
            inferred_type = "char*" if usage["assigned_through_pointer"] else "const char*"
            confidence = "high"
            reasons.append("pointer dereference/indexing plus string-like usage")
            return inferred_type, confidence, "; ".join(reasons)

        if current_type.endswith("*"):
            inferred_type = current_type
        else:
            inferred_type = "void*" if explicit_unknown else pointerize(current_type)
        confidence = "high"
        reasons.append("pointer-like body usage (*param / param[i] / arithmetic)")
        return inferred_type, confidence, "; ".join(reasons)

    if usage["used_in_string_func"] or usage["cast_to_char_ptr"] or usage["used_in_winapi_string_hint"]:
        inferred_type = "const char*"
        confidence = "medium"
        reasons.append("used with string APIs / char* cast")
        return inferred_type, confidence, "; ".join(reasons)

    if usage["used_in_memory_func"]:
        inferred_type = "void*" if not current_type.endswith("*") else current_type
        confidence = "medium"
        reasons.append("used with memory APIs")
        return inferred_type, confidence, "; ".join(reasons)

    return inferred_type, confidence, param.get("inference_reason", "taken from decompiler signature")


def infer_better_return_type(parsed: dict, body: str):
    current = normalize_type(parsed["return_type"])
    reasons = []

    if re.search(r"\breturn\s+0xffffffff\s*;", body) and current == "unsigned int":
        return "int", "medium", "returns 0xffffffff sentinel, likely signed error code"

    if re.search(r"\breturn\s+-1\s*;", body) and current == "unsigned int":
        return "int", "high", "returns -1 sentinel"

    return current, "high" if "undefined" not in parsed.get("original_return_type", "") else "low", "taken from decompiler signature"


def improve_types_from_body(parsed: dict, body: str):
    if not parsed:
        return parsed

    # forward export does not need params/return inference
    if parsed.get("kind") == "forward_export":
        return parsed

    if not body:
        return parsed

    ret_type, ret_conf, ret_reason = infer_better_return_type(parsed, body)
    parsed["return_type"] = ret_type
    parsed["return_type_confidence"] = ret_conf
    parsed["return_inference_reason"] = ret_reason

    improved = []
    for p in parsed["params"]:
        new_p = dict(p)
        inferred_type, conf, reason = infer_better_param_type(new_p, body)
        new_p["type"] = inferred_type
        new_p["type_confidence"] = conf
        new_p["inference_reason"] = reason
        improved.append(new_p)

    parsed["params"] = improved
    return parsed


# MAIN

def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_overrides_from_decompile_dump.py functions_dump.txt [overrides.json]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("overrides.generated.json")

    if not input_path.exists():
        print(f"[!] File not found: {input_path}")
        sys.exit(1)

    text = input_path.read_text(encoding="utf-8", errors="ignore")
    functions = extract_functions(text)

    overrides = {}

    for item in functions:
        parsed = parse_signature(item["signature"])
        if not parsed:
            continue

        parsed = improve_types_from_body(parsed, item["body"])
        fn = parsed["function_name"]
        overrides[fn] = parsed

    output_path.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"[+] Functions extracted: {len(functions)}")
    print(f"[+] Functions parsed: {len(overrides)}")
    print(f"[+] Written: {output_path}")


if __name__ == "__main__":
    main()