#!/usr/bin/env python3
"""Find hosts on one private /24 network that accept the configured SSH credentials."""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass


DEFAULT_PORT = 22
DEFAULT_JOBS = 16
DEFAULT_TIMEOUT = 1.0

# 直接在这里修改后运行：python3 scripts/find_ssh_hosts.py
# 密码会明文保存在本文件中；不要把填好密码的版本提交到 Git。
SSH_USERNAME = "用户名"
SSH_PASSWORD = "密码"
TARGET_NETWORK = "10.101.31.0/24"
SSH_PORT = DEFAULT_PORT
SCAN_JOBS = DEFAULT_JOBS
NETWORK_TIMEOUT_SECONDS = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class HostStatus:
    """A reachable host and the SSH checks completed for it."""

    address: ipaddress.IPv4Address
    ssh_open: bool
    ssh_authenticated: bool


def local_ipv4_address(destination: ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    """Return the source address selected specifically for a destination."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            # UDP connect selects a route locally; it does not send a packet.
            sock.connect((str(destination), 9))
            return ipaddress.IPv4Address(sock.getsockname()[0])
        except OSError as exc:
            raise RuntimeError(
                f"无法确定前往 {destination} 的本机 IPv4 地址；请检查网络连接。"
            ) from exc


def private_24_network(value: str) -> ipaddress.IPv4Network:
    """Parse and restrict the scan target to one private IPv4 /24."""
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("网络必须是 IPv4 CIDR，例如 10.101.31.0/24") from exc

    if not isinstance(network, ipaddress.IPv4Network):
        raise argparse.ArgumentTypeError("仅支持 IPv4 网络")
    if network.prefixlen != 24:
        raise argparse.ArgumentTypeError("为避免扩大扫描范围，仅支持 /24 网络")
    if not network.is_private:
        raise argparse.ArgumentTypeError("仅允许私有 IPv4 网络")
    return network


def tcp_open(address: ipaddress.IPv4Address, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((str(address), port), timeout=timeout):
            return True
    except OSError:
        return False


def ping_alive(address: ipaddress.IPv4Address, timeout: float) -> bool:
    """Return whether the host responds to one ICMP echo request."""
    try:
        completed = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", str(max(1, math.ceil(timeout))), str(address)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def ssh_login(
    address: ipaddress.IPv4Address,
    username: str,
    port: int,
    timeout: float,
    askpass: Path,
    known_hosts: Path,
) -> bool:
    environment = os.environ.copy()
    environment.update(
        {
            "SSH_ASKPASS": str(askpass),
            "SSH_ASKPASS_REQUIRE": "force",
            # OpenSSH requires DISPLAY for some SSH_ASKPASS configurations.
            "DISPLAY": environment.get("DISPLAY", "ssh-host-discovery"),
        }
    )
    command = [
        "setsid",
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "PasswordAuthentication=yes",
        "-o",
        "KbdInteractiveAuthentication=yes",
        "-o",
        f"ConnectTimeout={max(1, math.ceil(timeout))}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "LogLevel=ERROR",
        # Keep host keys only for this run.  accept-new avoids silently
        # accepting a changed key while still making first-contact discovery usable.
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        f"{username}@{address}",
        "true",
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            # SSH host-key negotiation and password authentication can be
            # slower than the short TCP discovery timeout on small devices.
            timeout=max(timeout + 4, 15),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def parse_args() -> argparse.Namespace:
    return argparse.ArgumentParser(
        description="根据本文件顶部配置在私有 /24 网段查找可登录的 SSH 设备。"
    ).parse_args()


def main() -> int:
    parse_args()
    try:
        username = SSH_USERNAME
        password = SSH_PASSWORD
        network = private_24_network(TARGET_NETWORK)
        port = SSH_PORT
        jobs = SCAN_JOBS
        timeout = NETWORK_TIMEOUT_SECONDS
    except (RuntimeError, argparse.ArgumentTypeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        print("错误：请在脚本顶部填写非空 SSH_USERNAME 和 SSH_PASSWORD。", file=sys.stderr)
        return 2
    if (
        isinstance(port, bool)
        or not isinstance(port, int)
        or isinstance(jobs, bool)
        or not isinstance(jobs, int)
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 1 <= port <= 65535
        or not 1 <= jobs <= 64
        or not 0.1 <= timeout <= 15
    ):
        print("错误：port=1..65535，jobs=1..64，timeout=0.1..15。", file=sys.stderr)
        return 2
    try:
        own_address = local_ipv4_address(next(network.hosts()))
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    temporary_directory = Path(tempfile.mkdtemp(prefix="ssh-host-discovery-"))
    password_file = temporary_directory / "password"
    askpass_file = temporary_directory / "askpass"
    known_hosts_file = temporary_directory / "known_hosts"
    try:
        password_descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(password_descriptor, "w", encoding="utf-8") as password_handle:
            password_handle.write(password)
        askpass_file.write_text(f"#!/bin/sh\nexec /bin/cat {password_file}\n", encoding="utf-8")
        askpass_file.chmod(0o700)

        candidates = [address for address in network.hosts() if address != own_address]
        own_description = f"跳过本机 {own_address}" if own_address in network else "本机不在目标网段"
        print(f"扫描 {network}（{own_description}），共 {len(candidates)} 个地址…")
        online_hosts: list[HostStatus] = []
        authenticated_hosts: list[HostStatus] = []

        def check(address: ipaddress.IPv4Address) -> HostStatus | None:
            ssh_open = tcp_open(address, port, timeout)
            if not ssh_open:
                return HostStatus(address, False, False) if ping_alive(address, timeout) else None
            return HostStatus(
                address,
                True,
                ssh_login(
                    address,
                    username,
                    port,
                    timeout,
                    askpass_file,
                    known_hosts_file,
                ),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
            for status in executor.map(check, candidates):
                if status is None:
                    continue
                online_hosts.append(status)
                if status.ssh_authenticated:
                    authenticated_hosts.append(status)
                    print(f"在线：{status.address}:{port}（SSH 登录成功）")
                elif status.ssh_open:
                    print(f"在线：{status.address}:{port}（SSH 端口开放，但登录未成功）")
                else:
                    print(f"在线：{status.address}（ping 有回应，SSH 端口未开放）")

        if not online_hosts:
            print("未发现可确认在线的设备。设备若禁用 ping 且未开放 SSH，不会显示。")
            return 1
        print(f"完成：在线 {len(online_hosts)} 台；SSH 登录成功 {len(authenticated_hosts)} 台。")
        return 0
    finally:
        # Includes the password, temporary SSH host keys, and askpass helper.
        shutil.rmtree(temporary_directory, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
