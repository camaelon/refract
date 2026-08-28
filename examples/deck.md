:: title
# RemoteCompose, from Markdown
A clean pipeline: markdown to components to .rc

---

:: section
# Part One: How it works

---

:: content
# The pipeline
refract parses this markdown into RemoteCompose component JSON.

The json2rc tool converts that JSON into binary .rc using the real
androidx remote-core library.

---

# Why components
No pixel math, no hand-rolled serializer.

The layout is done by the RemoteCompose engine, so the same document
plays back on the C++ desktop and the TypeScript player.
