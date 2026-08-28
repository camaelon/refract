:: title

<logo.png>

Markdown to RemoteCompose

---

:: include : intro

---

:: content
# Content types
refract renders several block types out of the box:

- text paragraphs
- bullet lists
  - including sub-bullets
- fenced code blocks
- image includes

---

# Code
```kotlin
fun greet(name: String) {
    println("Hello, $name")
}
```

---

# An image
<logo.png>

---

# A JSON include
<card.json>

---

:: content [2:3]
# Two panes (2:3)

Text on the left with a couple of points:
- first point
- second point

+++

<logo.png>

---

:: [1:1:1]
# Three panes (1:1:1)

Pane one text.

+++

- pane two
- bullets

+++

<logo.png>
