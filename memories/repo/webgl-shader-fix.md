# WebGL Shader Stripping Fix

## Problem
All CodeGamified games create materials at runtime via `ProceduralAssembler.FindFallbackShader()` which calls `Shader.Find("Universal Render Pipeline/Unlit")`. In WebGL builds, Unity strips shaders not statically referenced by any material. `Shader.Find()` returns null → materials don't load → magenta/invisible objects.

## Root Cause
- Pong was created from `com.unity.template.universal-2d@5.0.2` which includes a URP shader in Always Included Shaders
- All other games were created from `com.unity.template.urp-blank@17.0.11` which does NOT include it
- No scene materials statically reference URP/Unlit or URP/Lit — everything is procedural

## Fix
Add this line to `ProjectSettings/GraphicsSettings.asset` under `m_AlwaysIncludedShaders`:
```yaml
- {fileID: 4800000, guid: 650dd9526735d5b46b79224bc6e94025, type: 3}
```

This is the URP Lit shader from `com.unity.render-pipelines.universal@17.0.3` (Unity 6000.0.36f1).

## Automation
Run `python py/FIX_WEBGL_SHADERS.py --check` to verify all projects.
Run `python py/FIX_WEBGL_SHADERS.py --apply` to fix any missing entries.

## For New Games
When creating a new game from the URP Blank template, ALWAYS add the shader entry above to `GraphicsSettings.asset` before building for WebGL.
