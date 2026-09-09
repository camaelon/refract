:: title
# Making Coffee
*A very short talk, used by the refract tutorial*

---

:: section duration=3m
# Part One: The Beans

---

# What to buy
- Whole beans, not ground
- Roasted **within the last month**
- Something you can buy again

---

:: section duration=5m
# Part Two: The Method

---

# The ratio
*One part coffee to sixteen parts water*

<logo.png>

???
The ratio is the only number worth remembering. Everything else is taste.

---

:: content
# Grind, then brew

```python
def brew(beans_g, water_g=None):
    water_g = water_g or beans_g * 16
    return f"{beans_g}g beans, {water_g}g water"
```

---

:: max
# A live component

<card.json | title="Drawn by the engine, not a screenshot">

---

:: section duration=2m
# Part Three: Tasting

---

:: split
# Two things to notice
- Sweetness arrives first
- Bitterness is a timing problem

+++

- Sour means under-extracted
- Grind finer, or wait longer
