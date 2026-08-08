"""Python 3.12 新特性 Demo

涵盖以下 3.12 特性：
  - PEP 701: 更灵活的 f-string（多行、反斜杠、相同引号复用）
  - PEP 698: @override 显式覆写检查
  - PEP 695: 紧凑泛型语法 type / class / def 均支持 [T]
  - itertools.batched: 批量分组
  - pathlib.Path.walk: 原生目录遍历
  - typing.Self: 方法返回自身类型的正确标注
  - 改进的错误信息: 更聪明的 NameError / ImportError
"""

from pathlib import Path
from typing import Self, override
from itertools import batched

# =============================================================================
# 1. PEP 701 — 灵活的 f-string
# =============================================================================
print("═" * 50)
print("1. PEP 701 — 灵活的 f-string")
print("═" * 50)

hero = "Arthur"
weapon = "Excalibur"

# 内嵌和外层相同引号不再冲突
print(f"Sir {hero} shouted: "I am the king!"")
print(f'Sir {hero} whispered: \'I am scared\'')

# 表达式内部可以换行 + 注释
print(
    f"Verdict: {
        'worthy'
        if len(weapon) > 5   # 武器名够长就算配得上
        else 'unworthy'
    }"
)


# =============================================================================
# 2. PEP 698 — @override
# =============================================================================
print("\n" + "═" * 50)
print("2. PEP 698 — @override 显式覆写")
print("═" * 50)


class MusicPlayer:
    def play(self) -> str:
        return "♪ ♪ ♪"

    def stop(self) -> str:
        return "silence"


class VinylPlayer(MusicPlayer):
    @override
    def play(self) -> str:
        return "♫ crackle ♫"

    @override
    def stop(self) -> str:
        return "needle lifted"


vp = VinylPlayer()
print(f"play  → {vp.play()}")
print(f"stop  → {vp.stop()}")


# =============================================================================
# 3. PEP 695 — 紧凑泛型语法
# =============================================================================
print("\n" + "═" * 50)
print("3. PEP 695 — type / class / def [T]")
print("═" * 50)

type Pair[T] = tuple[T, T]


class Box[T]:
    def __init__(self, value: T) -> None:
        self.value = value


def pick[T](a: T, b: T, *, left: bool = True) -> T:
    return a if left else b


p: Pair[str] = ("hello", "world")
b = Box(42)
chosen = pick("apple", "banana", left=False)

print(f"Pair[str]    = {p}")
print(f"Box[int]     = {b.value}")
print(f"pick(…)      = {chosen}")


# =============================================================================
# 4. itertools.batched
# =============================================================================
print("\n" + "═" * 50)
print("4. itertools.batched — 批量分组")
print("═" * 50)

nums = range(1, 21)
for idx, chunk in enumerate(batched(nums, 6)):
    print(f"  chunk {idx}: {list(chunk)}")

# 最后一个 batch 自动变短
short = list(batched("abcde", 2))
print(f"  short batches: {short}")


# =============================================================================
# 5. pathlib.Path.walk
# =============================================================================
print("\n" + "═" * 50)
print("5. pathlib.Path.walk — 目录遍历")
print("═" * 50)

cwd = Path(".")
for dirpath, dirnames, filenames in cwd.walk():
    depth = len(dirpath.relative_to(cwd).parts)
    if depth > 1:
        continue
    prefix = "  " * depth
    print(f"{prefix}{dirpath.name}/")
    for f in sorted(filenames):
        print(f"{prefix}  {f}")
    if not filenames:
        print(f"{prefix}  (empty)")


# =============================================================================
# 6. typing.Self — 返回自身类型
# =============================================================================
print("\n" + "═" * 50)
print("6. typing.Self — 方法返回自身类型")
print("═" * 50)


class Counter:
    def __init__(self, start: int = 0) -> None:
        self.n = start

    def inc(self) -> Self:
        self.n += 1
        return self

    def dec(self) -> Self:
        self.n -= 1
        return self


c = Counter().inc().inc().dec()
print(f"Counter after inc().inc().dec() = {c.n}")


# =============================================================================
# 7. 更友好的错误信息
# =============================================================================
print("\n" + "═" * 50)
print("7. 更友好的错误信息")
print("═" * 50)

import sys

try:
    from collections import ordereddict
except ImportError as e:
    print(f"  ImportError → {e}")

try:
    standard = 3.14
    print(standart)
except NameError as e:
    print(f"  NameError  → {e}")

print("\n✅ 所有 Demo 运行完毕 (Python {0}.{1})".format(*sys.version_info[:2]))
