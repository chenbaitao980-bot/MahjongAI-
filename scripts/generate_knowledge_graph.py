#!/usr/bin/env python3
"""
GitNexus-like Knowledge Graph Generator
为 MahjongAI 项目生成知识图谱和架构文档
"""

import os
import json
import ast
import re
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple, Any

PROJECT_ROOT = Path("D:/claude/project/MahjongAI/MahjongAI")
OUTPUT_DIR = PROJECT_ROOT / ".workbuddy" / "knowledge-graph"

# ── 文件分类 ──────────────────────────────────────────────────
IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".workbuddy", "data", "logs", "tmp_frames", "debug", "debug_output"}
IGNORE_FILES = {"main.py", "mahjong_ai.spec"}


def scan_python_files(root: Path) -> List[Path]:
    """扫描所有 Python 文件"""
    py_files = []
    for p in root.rglob("*.py"):
        parts = set(p.relative_to(root).parts)
        if parts & IGNORE_DIRS:
            continue
        if p.name in IGNORE_FILES:
            continue
        py_files.append(p)
    return sorted(py_files)


def extract_module_info(filepath: Path) -> Dict:
    """提取模块的类和函数信息"""
    info = {"classes": [], "functions": [], "imports": [], "from_imports": []}
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                info["classes"].append({
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
                })
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                if node.col_offset == 0:  # 顶层函数
                    info["functions"].append({
                        "name": node.name,
                        "line": node.lineno,
                        "is_async": isinstance(node, ast.AsyncFunctionDef)
                    })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    info["from_imports"].append({
                        "module": module,
                        "name": alias.name,
                        "alias": alias.asname
                    })
    except Exception as e:
        info["error"] = str(e)
    return info


def find_file_references(root: Path, py_files: List[Path]) -> Dict[str, List[str]]:
    """查找文件之间的引用关系"""
    refs: Dict[str, List[str]] = defaultdict(list)
    file_contents = {}
    
    # 读取所有文件内容
    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                file_contents[fpath] = f.read()
        except:
            file_contents[fpath] = ""
    
    # 分析引用
    for fpath in py_files:
        rel = str(fpath.relative_to(root))
        content = file_contents[fpath]
        
        for other in py_files:
            if other == fpath:
                continue
            other_rel = str(other.relative_to(root))
            other_name = other.stem
            
            # 检查 import 引用
            patterns = [
                f"import {other_name}",
                f"from {other_name}",
                f"from .*{other_name}",
                other_name + ".",
            ]
            
            for pat in patterns:
                if re.search(pat, content):
                    refs[rel].append(other_rel)
                    break
    
    return dict(refs)


def build_knowledge_graph(py_files: List[Path], root: Path) -> Dict:
    """构建知识图谱"""
    graph = {
        "nodes": [],
        "edges": [],
        "modules": {},
        "stats": {}
    }
    
    all_classes = []
    all_functions = []
    module_deps = find_file_references(root, py_files)
    
    for fpath in py_files:
        rel = str(fpath.relative_to(root))
        info = extract_module_info(fpath)
        
        # 节点
        graph["nodes"].append({
            "id": rel,
            "type": "file",
            "classes": len(info["classes"]),
            "functions": len(info["functions"]),
            "size": fpath.stat().st_size if fpath.exists() else 0
        })
        
        # 模块信息
        graph["modules"][rel] = {
            "classes": [c["name"] for c in info["classes"]],
            "functions": [f["name"] for f in info["functions"]],
            "imports": info["imports"],
            "from_imports": info["from_imports"]
        }
        
        all_classes.extend([(rel, c["name"]) for c in info["classes"]])
        all_functions.extend([(rel, f["name"]) for f in info["functions"]])
    
    # 依赖边
    for src, deps in module_deps.items():
        for dst in deps:
            graph["edges"].append({
                "source": src,
                "target": dst,
                "type": "imports"
            })
    
    # 统计
    graph["stats"] = {
        "total_files": len(py_files),
        "total_classes": len(all_classes),
        "total_functions": len(all_functions),
        "total_edges": len(graph["edges"])
    }
    
    return graph


def generate_mermaid_graph(graph: Dict) -> str:
    """生成 Mermaid 图"""
    lines = ["graph TD"]
    lines.append("    %% MahjongAI 知识图谱")
    lines.append("")
    
    # 按目录分组
    dirs = defaultdict(list)
    for node in graph["nodes"]:
        fpath = node["id"]
        # 简化为目录/文件名
        parts = fpath.split("/")
        if len(parts) > 1:
            group = parts[0]
        else:
            group = "root"
        dirs[group].append(fpath)
    
    # 生成子图
    for group, files in dirs.items():
        lines.append(f"    subgraph {group}_grp[{group}/]")
        for f in files[:15]:  # 限制数量
            name = f.split("/")[-1].replace(".py", "")
            lines.append(f"        {name}[{name}]")
        lines.append("    end")
        lines.append("")
    
    # 生成边（限制数量）
    for i, edge in enumerate(graph["edges"][:50]):
        src = edge["source"].split("/")[-1].replace(".py", "")
        dst = edge["target"].split("/")[-1].replace(".py", "")
        lines.append(f"    {src} --> {dst}")
    
    return "\n".join(lines)


def generate_architecture_doc(graph: Dict, root: Path) -> str:
    """生成架构文档"""
    lines = ["# MahjongAI 知识图谱\n"]
    lines.append(f"> 自动生成于 {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append("## 统计概览\n")
    stats = graph["stats"]
    lines.append(f"- **Python 文件**: {stats['total_files']}")
    lines.append(f"- **类数量**: {stats['total_classes']}")
    lines.append(f"- **函数数量**: {stats['total_functions']}")
    lines.append(f"- **依赖关系**: {stats['total_edges']}")
    lines.append("")
    
    lines.append("## 模块拓扑\n")
    # 按文件大小排序
    sorted_nodes = sorted(graph["nodes"], key=lambda x: x["size"], reverse=True)
    lines.append("| 文件 | 类 | 函数 | 大小 |")
    lines.append("|------|----|------|------|")
    for node in sorted_nodes[:30]:
        f = node["id"].split("/")[-1]
        lines.append(f"| `{f}` | {node['classes']} | {node['functions']} | {node['size']//1024}KB |")
    lines.append("")
    
    lines.append("## 核心类\n")
    for fpath, info in list(graph["modules"].items())[:20]:
        if info["classes"]:
            f = fpath.split("/")[-1]
            for cls in info["classes"][:5]:
                lines.append(f"- **{f}** → `{cls}`")
    lines.append("")
    
    lines.append("## 依赖关系（Top 30）\n")
    for edge in graph["edges"][:30]:
        src = edge["source"].split("/")[-1]
        dst = edge["target"].split("/")[-1]
        lines.append(f"- `{src}` → `{dst}`")
    
    return "\n".join(lines)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"[1/4] 扫描 Python 文件...")
    py_files = scan_python_files(PROJECT_ROOT)
    print(f"    找到 {len(py_files)} 个文件")
    
    print(f"[2/4] 构建知识图谱...")
    graph = build_knowledge_graph(py_files, PROJECT_ROOT)
    print(f"    节点: {len(graph['nodes'])}, 边: {len(graph['edges'])}")
    
    print(f"[3/4] 生成图谱数据...")
    graph_file = OUTPUT_DIR / "knowledge-graph.json"
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    print(f"    保存到 {graph_file}")
    
    print(f"[4/4] 生成架构文档...")
    arch_doc = generate_architecture_doc(graph, PROJECT_ROOT)
    arch_file = PROJECT_ROOT / "architecture.md"
    with open(arch_file, "w", encoding="utf-8") as f:
        f.write(arch_doc)
    print(f"    更新 {arch_file}")
    
    # 生成 Mermaid 图
    mermaid = generate_mermaid_graph(graph)
    mermaid_file = OUTPUT_DIR / "graph.mmd"
    with open(mermaid_file, "w", encoding="utf-8") as f:
        f.write(mermaid)
    print(f"    生成 Mermaid 图: {mermaid_file}")
    
    print("\n完成！")
    print(f"  图谱数据: {graph_file}")
    print(f"  架构文档: {arch_file}")
    print(f"  Mermaid:  {mermaid_file}")


if __name__ == "__main__":
    main()
