#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写手线原子写的最后一格：把**改名本身**也落盘（F-R530-01）。

## 这是在补什么

写手线有五处原子写（singleflight 闸、dispatcher 的 `_atomic_write_json` 与
`acquire_lock`、`episode_stage_gate_runner` 的门摘要、`gate_result_contract`
的门结果）。F-R525-01 把「写活件」改成「写临时件 + `os.replace`」，消灭了进程
崩溃留下的半截文件；F-R529-01 又给唯一漏网的 singleflight 补上 `flush` +
`fsync`，让**文件内容**在机器崩溃后也确定在盘上。

到此为止，**文件内容**是持久的，**改名**不是。`os.replace` 改的是目录项，
目录项跟普通文件数据一样先待在页缓存里。掉电/内核崩溃可以留下这样一台机器：
新内容的数据块已落盘，但指向它的那条目录项没有 —— 重启后看到的是**旧字节**
（或者对 `acquire_lock` 这种新建件而言，**文件根本不存在**）。

对写手线的具体后果按件而异，且都被「旧的完整字节」兜住，因此**不是数据损坏，
是提交丢失**：

* singleflight 闸：`release` 丢失 ⇒ 闸停在 ACTIVE，下一轮空转到 120 分钟过期
  才放行；`claim` 丢失 ⇒ 两轮可同时认为自己持锁（正是本闸要防的那件事）。
* `acquire_lock`：写锁的创建丢失 ⇒ 同集同版本的独占租约在崩溃后形同没取过。
* receipt / 门摘要 / 门结果：终态回退成前一态，需要重跑；SHA 绑定仍自洽，
  不会出现「绑了一份不存在的字节」。

## 为什么单独成模块

五处原子写是五份互相抄来的代码，`fsync` 那次就是因此漏了一处 —— 而漏的偏偏
是保护其余四处的那道闸。同一风险修第三次的时候，把判据收进**一处实现**比再抄
一遍更能防住下一次漂移。本模块只做这一件事，零依赖，可被五处同时调用。

## 一条不可让步的约束

目录 `fsync` **永不抛异常**。调用到这里时 `os.replace` 已经成功，提交已经发生；
把一次成功的提交因为「刷目录失败」翻成异常，比不刷更糟 —— 那会让调用方误以为
写盘失败并去回滚一个**已经生效**的状态。故：尽力刷，刷不动就如实返回 False，
由调用方决定要不要记，绝不改变调用方看到的控制流。
"""

from __future__ import annotations

import os
import pathlib
from typing import Union

PathLike = Union[str, "os.PathLike[str]", pathlib.Path]

__all__ = ["fsync_directory", "durable_replace"]


def fsync_directory(directory: PathLike) -> bool:
    """尽力把目录项刷到盘上。**绝不抛异常**，只用返回值说话。

    返回 True = 目录项已落盘；False = 本平台/本文件系统刷不动（例如不支持
    对目录 fsync，或目录已不存在）。False 不代表前一步的写失败。
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(os.fspath(directory), flags)
    except OSError:
        return False
    try:
        os.fsync(descriptor)
        return True
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def durable_replace(temporary: PathLike, target: PathLike) -> bool:
    """`os.replace` 之后把父目录项也落盘。

    次序不可换：**先 replace 再刷目录**。replace 之前刷目录毫无意义（那条目录项
    还没改），而 replace 仍然是最后一个会改变调用方可见状态的动作 —— 目标件要么
    是旧的完整字节、要么是新的完整字节，这一点与改前逐字相同。

    `os.replace` 自身的异常**原样上抛**（它意味着提交没有发生，调用方的清理阶梯
    该照常跑）；只有目录 fsync 的失败被吞掉，理由见模块文档。

    返回值＝目录项是否确认落盘，调用方可忽略。
    """
    os.replace(os.fspath(temporary), os.fspath(target))
    return fsync_directory(pathlib.Path(os.fspath(target)).parent)
