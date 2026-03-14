# CodeGamified

Open-source boilerplate for building **educational coding video games** in Unity.

Players write real code (Python subset) to control in-game systems — satellites, ships, robots, whatever your game needs. The engine compiles it to bytecode, executes it in a sandboxed VM, and renders feedback through retro terminal UIs. You supply the game; we supply the programming loop.

## What You Get

| Module | What It Does |
|---|---|
| **[.engine/CodeGamified.Engine](.engine/CodeGamified.Engine)** | Python subset → AST → RISC-like bytecode → time-scale-aware executor. 27 core opcodes + 32 game-customizable I/O opcodes. |
| **[.engine/CodeGamified.TUI](.engine/CodeGamified.TUI)** | Row-based monospace terminal UI → TextMeshPro rich-text. Scramble animations, progress bars, gradient colorization, resizable panels, slider/button overlays. |
| **[.engine/CodeGamified.Time](.engine/CodeGamified.Time)** | Simulation clock with pause/scale presets, time warp state machine (accelerate → cruise → decelerate → arrive), day/night hooks. |

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│  YOUR GAME (BitNaughts, SeaRauber, Pong, yours next)    │
│                                                         │
│  ICompilerExtension ─── game builtins, known types      │
│  IGameIOHandler ─────── sensor reads, signals, orders   │
│  TerminalWindow ─────── ship log, nav chart, debugger   │
│  SimulationTime ─────── day length, max warp speed      │
├─────────────────────────────────────────────────────────┤
│  .engine/ (git submodules — shared across all games)    │
│                                                         │
│  CodeGamified.Engine    compiler + VM + bytecode        │
│  CodeGamified.TUI       terminal rendering + animation  │
│  CodeGamified.Time      simulation clock + time warp    │
└─────────────────────────────────────────────────────────┘
```

Players write Python in a terminal. The engine compiles and runs it. The TUI shows the output. Time controls let players fast-forward simulations. Every game gets the same core loop — different theme, different builtins, same learning outcomes.

## Quick Start

```bash
# Fork this repo, then in your Unity project:
git submodule add https://github.com/CodeGamified/.engine.git Assets/.engine

# Implement 3 interfaces:
# 1. ICompilerExtension  → register your game's builtins (e.g. radio.send())
# 2. IGameIOHandler      → execute your custom opcodes at runtime
# 3. TerminalWindow      → define your terminal panels (Render() override)
#
# Ship it.
```

## Repo Structure

```
codegamified.github.io/          ← you are here (org landing page + submodule refs)
├── .engine/                     ← shared engine submodule
│   ├── CodeGamified.Engine/       compiler, VM, bytecode executor
│   ├── CodeGamified.TUI/          terminal UI framework
│   └── CodeGamified.Time/         simulation time + time warp
├── .github/                     ← org profile + agent instructions
└── pong/                        ← example game (submodule)
```

## Games Using This

| Game | Theme | Players Code To... |
|---|---|---|
| **BitNaughts** | GPU satellite tycoon | Program satellite sensors, transmissions, orbital maneuvers |
| **SeaRauber** | Pirate adventure | Automate crew orders, navigation, ship systems |
| **Pong** | Classic arcade | Control paddles via code |

## Why

Most "learn to code" products are glorified tutorials. Games teach better because **the feedback loop is intrinsic** — your code either steers the ship or it doesn't. No grades, no hints, no hand-holding. Just a terminal and a problem.

This boilerplate handles the hard parts (compilation, execution, sandboxing, time simulation, terminal rendering) so game developers can focus on the fun parts (world, narrative, game mechanics).

## License

See individual module READMEs for details.