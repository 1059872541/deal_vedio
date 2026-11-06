# -*- coding: utf-8 -*-
"""
字幕文件监控脚本
每10秒轮询目录，检测新出现的txt文件
"""
import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Callable

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from deal_video_agent.agent.subtitle_agent import run_subtitle_agent, print_result


class SubtitleMonitor:
    """字幕文件监控器"""
    
    def __init__(self, watch_dir: str, poll_interval: int = 10):
        self.watch_dir = Path(watch_dir)
        self.poll_interval = poll_interval
        self.processed_files: set = set()
        self._running = False
        self._callback: Optional[Callable] = None
        
        # 初始化时扫描已有文件
        self._scan_existing_files()
    
    def _scan_existing_files(self):
        """扫描已有文件"""
        if not self.watch_dir.exists():
            return
        
        for f in self.watch_dir.glob("*.txt"):
            if self._is_valid_subtitle_file(f.name):
                self.processed_files.add(f.name)
        
        print(f"监控目录: {self.watch_dir}")
        print(f"已有字幕文件: {len(self.processed_files)} 个")
    
    def _is_valid_subtitle_file(self, filename: str) -> bool:
        """检查是否为有效的字幕文件"""
        # 排除特定模式
        exclude_patterns = ["_ordered", "corrected", "_corrected"]
        
        for pattern in exclude_patterns:
            if pattern in filename:
                return False
        
        return filename.endswith(".txt")
    
    def _find_new_files(self) -> list[Path]:
        """查找新文件"""
        new_files = []
        
        if not self.watch_dir.exists():
            return new_files
        
        for f in self.watch_dir.glob("*.txt"):
            if self._is_valid_subtitle_file(f.name) and f.name not in self.processed_files:
                new_files.append(f)
        
        return new_files
    
    def _on_file_detected(self, file_path: Path):
        """检测到新文件时的处理"""
        print(f"\n{'='*50}")
        print(f"检测到新字幕文件: {file_path.name}")
        print(f"{'='*50}")
        
        # 标记为已处理
        self.processed_files.add(file_path.name)
        
        # 执行工作流
        self._run_workflow(file_path.parent)
    
    def _run_workflow(self, target_dir: str):
        """运行字幕纠正工作流"""
        # 提取合集名称
        folder_name = Path(target_dir).name
        
        # 构建用户提示词（简化版本）
        user_prompt = f"本次视频主要内容关于【暮色森林】..."
        
        print(f"\n开始执行字幕纠正工作流...")
        print(f"目标目录: {target_dir}")
        print(f"提示词: {user_prompt}\n")
        
        try:
            result = run_subtitle_agent(
                target_dir=target_dir,
                user_prompt=user_prompt
            )
            
            print_result(result)
            
        except Exception as e:
            print(f"工作流执行失败: {e}")
            import traceback
            traceback.print_exc()
    
    def start(self):
        """开始监控"""
        self._running = True
        print(f"\n开始监控 (每 {self.poll_interval} 秒轮询一次)")
        print("按 Ctrl+C 停止监控\n")
        
        try:
            while self._running:
                new_files = self._find_new_files()
                
                if new_files:
                    for f in new_files:
                        self._on_file_detected(f)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] 未检测到新文件...", end="\r")
                
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            print("\n\n监控已停止")
            self._running = False
    
    def stop(self):
        """停止监控"""
        self._running = False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="字幕文件监控器")
    parser.add_argument(
        "-d", "--dir", 
        default=r"D:\VedioRecords\工作区\我的世界\合集\合集十\剪辑",
        help="监控目录路径"
    )
    parser.add_argument(
        "-t", "--time",
        type=int,
        default=10,
        help="轮询间隔（秒）"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="立即执行，不等待新文件"
    )
    
    args = parser.parse_args()
    
    monitor = SubtitleMonitor(args.dir, args.time)
    
    if args.now:
        # 立即执行模式
        print("立即执行模式：直接运行工作流")
        monitor._run_workflow(args.dir)
    else:
        # 监控模式
        monitor.start()


if __name__ == "__main__":
    main()
