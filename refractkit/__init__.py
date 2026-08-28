"""refractkit — markdown slide deck → RemoteCompose component JSON.

Modules:
  settings   load settings.toml
  theme      Theme (colours + code styling) built from settings
  markdown   slide markdown -> {meta, title, blocks}
  deck       load slides.md, expand deck includes, resolve content includes
  images     image dimensions + contained bitmap canvas
  highlight  syntax highlighting (language registry)
  render     blocks + theme -> RemoteCompose component JSON
  components low-level component builders
"""
