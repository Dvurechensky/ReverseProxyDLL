<div align="center" style="margin: 20px 0; padding: 10px; background: #1c1917; border-radius: 10px;">
  <strong>🌐 Language: </strong>
  
  <a href="./README.ru.md" style="color: #F5F752; margin: 0 10px;">
    🇷🇺 Russian
  </a>
  | 
  <span style="color: #0891b2; margin: 0 10px;">
    ✅ 🇺🇸 English (current)
  </span>
</div>

<div align="center">
  <picture>
    <img src="https://github.com/7oSkaaa/7oSkaaa/blob/main/Images/about_me.gif?raw=true" width="100px">
  </picture>
  <h2>💻 ReverseProxyDLL</span></h2>
</div>

[![Status](https://shields.dvurechensky.pro/badge/status-active-brightgreen)](https://github.com/Dvurechensky/ReverseProxyDLL)
[![Platform](https://shields.dvurechensky.pro/badge/platform-windows%20x86-blue)](https://github.com/Dvurechensky/ReverseProxyDLL)
[![Focus](https://shields.dvurechensky.pro/badge/focus-legacy%20reverse%20proxy%20dll-purple)](https://github.com/Dvurechensky/ReverseProxyDLL)
[![Toolchain](https://shields.dvurechensky.pro/badge/toolchain-vc%2B%2B%202003%20first-orange)](https://github.com/Dvurechensky/ReverseProxyDLL)

> Generate reverse-aware proxy DLL scaffolds for legacy x86 Windows binaries from export dumps and decompiler output.

---

- [Startup](docs/STARTUP.md)
- [Русская версия](README.ru.md)

---

- [Why I built this](#why-i-built-this)
- [What this project does](#what-this-project-does)
- [What makes it different from ordinary DLL proxy generators](#what-makes-it-different-from-ordinary-dll-proxy-generators)
- [Current workflow](#current-workflow)
- [Toolchain / target scope](#toolchain--target-scope)
- [Core tools](#core-tools)
  - [`generate_overrides_from_ghidra_dump.py`](#generate_overrides_from_ghidra_dumppy)
  - [`reverse_dll_project_generator.py`](#reverse_dll_project_generatorpy)
- [Example workflow](#example-workflow)
- [What this project is **not**](#what-this-project-is-not)
- [Good fit for](#good-fit-for)
- [Status](#status)
- [Roadmap](#roadmap)

---

## Why I built this

I started this project while working on old Windows x86 binaries that were never meant to be pleasant to reconstruct.

The same problem kept repeating:

- export tables are **not enough**
- decompiler output is **not enough**
- writing a compatible proxy DLL **by hand** is slow and repetitive
- trying to fully reconstruct the original source too early is usually a dead end

So instead of rebuilding the same glue code every time, I built a workflow that gives me a **working proxy DLL scaffold first** — and only then I refine ABI, calling conventions, signatures, and real logic.

That was the exact problem I wanted to solve.

---

## What this project does

ReverseProxyDLL helps generate a **buildable compatibility scaffold** for an existing legacy x86 Windows DLL.

It can generate a proxy project that:

- loads the original DLL at runtime
- resolves exports with `GetProcAddress`
- forwards compatible calls
- keeps ordinals and export layout under control
- supports runtime logging and tracing
- gives me a structured base for reverse reconstruction

This lets me stop wasting time on repetitive boilerplate and focus on the actual `reverse engineering` work.

---

## What makes it different from ordinary DLL proxy generators

Most DLL proxy generators only do this:

- read export table
- generate wrappers
- forward calls

That is useful — but for real legacy reverse engineering, it is usually not enough.

This project is designed around a more practical workflow:

- **export-aware**
- **ABI-aware**
- **reverse-oriented**
- **manual-override friendly**

It understands that not all exports are the same.

For example, it can treat exports as:

- regular C exports
- C++ scoped / mangled exports
- data exports
- CRT / runtime forward exports

That distinction matters a lot when dealing with old x86 Windows DLLs.

---

## Current workflow

Typical workflow looks like this:

1. Dump exports from the original DLL
2. Inspect / decompile functions in Ghidra
3. Generate overrides / signatures
4. Generate proxy scaffold
5. Build replacement DLL
6. Launch target application
7. Refine ABI and logic incrementally

That means I no longer start from zero every time.

I start from a **working 80–90% scaffold** and iterate from there.

---

## Toolchain / target scope

This project is **legacy-first by design**.

It was originally built around:

- **Windows x86**
- **older native DLLs**
- **Visual C++ 2003 / VC7.1 style compatibility**
- reverse workflows where ABI correctness matters more than modern build convenience

The generated scaffold is intentionally kept simple and low-level, so parts of it can also be adapted to newer MSVC environments.

But to be precise:

> this project is currently aimed first at **legacy x86 Windows DLL reconstruction and proxy compatibility work**.

If it also works cleanly for a newer target — great.  
But the primary design goal is old-school Windows binary compatibility.

---

## Core tools

### [`generate_overrides_from_ghidra_dump.py`](src/generate_overrides_from_ghidra_dump.py)

Parses Ghidra-style decompiler output and generates structured `overrides.json` metadata.

Useful for:

- extracting signatures
- normalizing pseudo-types
- detecting calling conventions
- generating override-ready function definitions

### [`reverse_dll_project_generator.py`](src/reverse_dll_project_generator.py)

Generates a reverse-aware proxy DLL scaffold from export metadata and optional overrides.

Useful for:

- proxy DLL generation
- export wrapper scaffolding
- DEF/export layout control
- legacy DLL replacement workflows

---

## Example workflow

A typical run looks like this:

```bash
python src/generate_overrides_from_ghidra_dump.py functions_dump.c overrides.generated.json
python src/reverse_dll_project_generator.py exports.md -o generated_proxy --dll-name dacom --original-dll dacom_addon.dll --overrides overrides.generated.json
```

For full setup and build steps, see [Startup](docs/STARTUP.md).

---

## What this project is **not**

This tool does **not** magically reconstruct the full original source code.

It does **not** guarantee that every signature is automatically correct.

It does **not** replace actual reverse engineering.

What it does is something more practical:

> it gives you a fast, structured, buildable starting point for binary-compatible reconstruction.

---

## Good fit for

- reverse engineering old Windows x86 DLLs
- building compatibility wrappers
- legacy game / tool reconstruction
- ABI investigation
- DLL replacement experiments
- runtime tracing and controlled migration away from original binaries

---

## Status

This project is actively evolving around real-world legacy DLL reconstruction work.

The main goal is simple:

> reduce the time between “I have a binary” and “I have a working proxy-compatible scaffold”.

---

## Roadmap

- better override generation
- cleaner C++ export handling
- safer type inference
- improved DEF generation
- better legacy toolchain support
- tighter Ghidra-assisted workflows
