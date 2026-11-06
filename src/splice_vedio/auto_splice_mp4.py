# auto_splice_mp4.py
# 视频自动拼接脚本 - v4
# 功能：监听多目录，自动分割长视频，为每个片段添加片头片尾，生成最终视频
# 
# 新增功能 (v4):
# - WATCH_DIRECTORIES 每个目录可单独配置 start_video 和 end_video
# - 目录级配置优先于全局配置，如果目录未配置则使用全局配置
# 
# 配置示例:
# WATCH_DIRECTORIES = {
#     r"D:\video\dir1": {
#         'watch_duration': 20,
#         'start_video': r"D:\video\custom_start.mp4",  # 可选，未配置则使用全局
#         'end_video': r"D:\video\custom_end.mp4",      # 可选，未配置则使用全局
#     },
#     r"D:\video\dir2": {
#         'watch_duration': 20,
#         # 未配置 start_video/end_video，将使用全局配置
#     }
# }

import os
import subprocess
import math
import time
import json
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
import logging
from queue import Queue, Empty
from threading import Event

# ===== 配置参数 =====
# 多目录监听配置
# 每个目录可单独配置片头片尾，未配置时使用全局配置
WATCH_DIRECTORIES = {
    r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集六": {
        'watch_duration': 20,  # 该目录监听时长(秒)
        'input_dir': "剪辑",   # 可选：长视频来源子目录（默认 "剪辑"）
        'output_dir': "成片",  # 可选：处理输出子目录（默认 "成片"）
        'start_video': r"D:\VedioRecords\工作区\我的世界-2026-06\片头\2026-06-MC-678-开头.mp4",  # 可选，未配置则使用全局
        # 'end_video': ...,   # 可选，未配置则使用全局
    },
    r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集七": {
        'watch_duration': 20,  # 该目录监听时长(秒)
        'input_dir': "剪辑",   # 可选：长视频来源子目录（默认 "剪辑"）
        'output_dir': "成片",  # 可选：处理输出子目录（默认 "成片"）
        'start_video': r"D:\VedioRecords\工作区\我的世界-2026-06\片头\2026-06-MC-678-开头.mp4",  # 可选，未配置则使用全局
        # 'end_video': ...,   # 可选，未配置则使用全局
    },
    r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集八": {
        'watch_duration': 20,  # 该目录监听时长(秒)
        'input_dir': "剪辑",   # 可选：长视频来源子目录（默认 "剪辑"）
        'output_dir': "成片",  # 可选：处理输出子目录（默认 "成片"）
        'start_video': r"D:\VedioRecords\工作区\我的世界-2026-06\片头\2026-06-MC-678-开头.mp4",  # 可选，未配置则使用全局
        # 'end_video': ...,   # 可选，未配置则使用全局
    },
    r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集九": {
        'watch_duration': 20,  # 该目录监听时长(秒)
        'input_dir': "剪辑",   # 可选：长视频来源子目录（默认 "剪辑"）
        'output_dir': "成片",  # 可选：处理输出子目录（默认 "成片"）
        'start_video': r"D:\VedioRecords\工作区\我的世界-2026-06\片头\2026-06-MC-9-10-开头.mp4",  # 可选，未配置则使用全局
        # 'end_video': ...,   # 可选，未配置则使用全局
    },
    r"D:\VedioRecords\工作区\我的世界-2026-06\合集\合集十": {
        'watch_duration': 20,  # 该目录监听时长(秒)
        'input_dir': "剪辑",   # 可选：长视频来源子目录（默认 "剪辑"）
        'output_dir': "成片",  # 可选：处理输出子目录（默认 "成片"）
        'start_video': r"D:\VedioRecords\工作区\我的世界-2026-06\片头\2026-06-MC-9-10-开头.mp4",  # 可选，未配置则使用全局
        # 'end_video': ...,   # 可选，未配置则使用全局
    }
}

def get_resolved_path(dir_key, config, field, default_subdir):
    """解析配置中可选路径字段，支持相对子目录名和绝对路径

    Args:
        dir_key: WATCH_DIRECTORIES 的 key（父目录）
        config: 该 key 对应的配置字典
        field: 字段名（input_dir / output_dir）
        default_subdir: 字段缺失时的默认子目录名

    Returns:
        解析后的完整路径
    """
    value = config.get(field)
    if value is None:
        return os.path.join(dir_key, default_subdir) if default_subdir else dir_key
    if os.path.isabs(value):
        return value
    return os.path.join(dir_key, value)

# 全局片头片尾 - 必须是完整的文件路径
START_VIDEO = r""
END_VIDEO = r"D:\VedioRecords\工作区\我的世界-2026-06\片尾\2026-06-MC-结尾.mp4"

# 监听配置
WATCHER_THREAD_INTERVAL = 5  # 监听线程轮询间隔(秒)
FILE_STABLE_DURATION = 10  # 文件就绪检查的稳定时间

# 处理配置  
SEGMENT_DURATION = 360  # 长视频分割成短视频，每段短视频的时长 6分
DURATION_TOLERANCE = 3  # ±3秒 在关键帧分割，允许的短视频时长波动范围
MAX_CONCURRENT_CONCAT = 2  # 最大并行拼接任务数
PROCESSOR_THREADS = 2  # 处理线程数
MAX_RETRY_COUNT = 2  # 最大重试次数

# 元数据文件
METADATA_FILE = "video_processing_metadata.json"
LOG_FILE = "video_processing.log"

# 视频参数
VIDEO_PARAMS = {
    'resolution': '1920x1080',
    'framerate': '25',
    'pix_fmt': 'yuv420p',
    'color_primaries': 'bt709',
    'color_trc': 'bt709',
    'colorspace': 'bt709',
    'audio_codec': 'aac',
    'audio_bitrate': '128k'
}

# 编码器优先级配置
ENCODER_PRIORITY = [
    # {
    #     'name': 'libx264',
    #     'quality_param': '-crf', 
    #     'quality_value': '23',
    #     'preset': 'medium',
    #     'extra_args': []
    # },
    {
        'name': 'h264_qsv', 
        'quality_param': '-global_quality',
        'quality_value': '23',
        'preset': 'medium',
        'extra_args': []
    }
]

# 全局变量，存储FFmpeg版本信息
FFMPEG_VERSION_LOGGED = False


def get_directory_intro_ending(dir_path):
    """
    获取目录的片头片尾配置
    
    优先级：目录级配置 > 全局配置
    如果目录配置中未设置 start_video 或 end_video，则使用全局配置
    
    Args:
        dir_path: 目录路径
        
    Returns:
        tuple: (start_video, end_video) 文件路径
    """
    dir_path = os.path.normpath(dir_path)
    
    if dir_path in WATCH_DIRECTORIES:
        config = WATCH_DIRECTORIES[dir_path]
        start_video = config.get('start_video', None)
        end_video = config.get('end_video', None)
        
        # 如果目录级配置未设置，则使用全局配置
        if start_video is None:
            start_video = START_VIDEO
        if end_video is None:
            end_video = END_VIDEO
            
        return start_video, end_video
    
    # 不在配置中，使用全局配置
    return START_VIDEO, END_VIDEO


# ===== 初始化日志系统 =====
def setup_logging():
    """配置双通道日志系统（覆盖模式）"""
    # 创建日志目录
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # 确保每次运行都覆盖旧日志
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except Exception as e:
            logging.warning(f"无法删除旧日志文件: {e}")
    
    # 创建日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # 捕获所有级别日志
    
    # 清除已有处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 文件日志处理器 - 详细日志（覆盖模式）
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # 控制台日志处理器 - 仅显示重要信息
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(console_formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()
user_logger = logging.getLogger("user")  # 用于用户可见信息

def log_separator(title="", level="main", logger=None):
    """
    在日志中添加视觉分隔符
    
    Parameters:
    title (str): 分隔符中间的标题文本
    level (str): 分隔级别 - 'main'、'sub'、'segment'
    logger (Logger): 要使用的日志记录器，如果为None则使用全局logger
    """
    if logger is None:
        logger = logging.getLogger()
    
    if level == "main":
        # 主分隔符 (用于新视频/主要阶段)
        separator_char = "="
        separator_width = 60
    elif level == "sub":
        # 子分隔符 (用于处理阶段)
        separator_char = "-"
        separator_width = 60
    elif level == "segment":
        # 段落分隔符 (用于单个片段)
        separator_char = "."
        separator_width = 40
    else:
        separator_char = "*"
        separator_width = 60
    
    # 计算标题两侧的分隔符长度
    title_length = len(title) + 2 if title else 0  # +2 用于两侧空格
    separator_length = (separator_width - title_length) // 2
    
    if title:
        separator_line = f"{separator_char * separator_length} {title} {separator_char * separator_length}"
        # 确保总长度一致
        if len(separator_line) < separator_width:
            separator_line += separator_char * (separator_width - len(separator_line))
    else:
        separator_line = separator_char * separator_width
    
    logger.info(separator_line)


# ===== 工具函数 =====
def get_current_time():
    """获取当前时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def format_duration(seconds):
    """格式化耗时(秒)为易读的字符串"""
    if seconds < 60:
        return f"{seconds:.2f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        seconds = seconds % 60
        return f"{minutes}分{seconds:.2f}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        return f"{hours}小时{minutes}分{seconds:.2f}秒"

def get_video_duration(input_video):
    """使用ffprobe获取视频时长(秒)"""
    start_time = time.time()
    logger.debug(f"开始获取视频时长: {input_video}")
    
    cmd = [
        'ffprobe', '-i', input_video, 
        '-show_entries', 'format=duration', 
        '-v', 'quiet', 
        '-of', 'csv=p=0'
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        duration = float(result.stdout.strip())
        end_time = time.time()
        logger.debug(f"获取视频时长完成: {duration}秒, 耗时: {format_duration(end_time - start_time)}")
        return duration
    except Exception as e:
        end_time = time.time()
        logger.error(f"获取视频时长时出错: {e}, 耗时: {format_duration(end_time - start_time)}")
        return 0

def is_file_ready(filepath: str, stable_duration: int = FILE_STABLE_DURATION) -> bool:
    """检查文件是否写入完成：连续 stable_duration 秒大小不变"""
    if not os.path.exists(filepath):
        return False
    try:
        size1 = os.path.getsize(filepath)
        logger.debug(f"文件大小检查: {filepath} - 初始大小: {size1} bytes")
        time.sleep(stable_duration)
        size2 = os.path.getsize(filepath)
        logger.debug(f"文件大小检查: {filepath} - 稳定后大小: {size2} bytes")
        result = size1 == size2 and size1 > 0
        if result:
            logger.info(f"文件就绪: {filepath}")
        else:
            logger.warning(f"文件未就绪或仍在写入: {filepath}")
        return result
    except (OSError, FileNotFoundError) as e:
        logger.error(f"文件就绪检查出错: {filepath}, 错误: {e}")
        return False

def log_ffmpeg_version():
    """记录 FFmpeg 版本信息（只需一次）"""
    global FFMPEG_VERSION_LOGGED
    if FFMPEG_VERSION_LOGGED:
        return
    
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            timeout=10
        )
        # 只取前10行核心信息，避免日志过长
        version_info = '\n'.join(result.stdout.splitlines()[:10])
        logger.info(f"FFmpeg 版本信息:\n{version_info}")
        FFMPEG_VERSION_LOGGED = True
        return True
    except Exception as e:
        logger.error(f"获取 FFmpeg 版本信息失败: {e}")
        return False

def log_ffmpeg_error(e: Exception, operation: str):
    """
    优化的 FFmpeg 错误记录，只保留关键错误信息
    """
    if isinstance(e, subprocess.TimeoutExpired):
        logger.error(f"{operation} 超时（超过 {e.timeout} 秒）")
        return
        
    if isinstance(e, subprocess.CalledProcessError):
        # 提取关键错误行
        stderr_str = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
        
        # 优先查找包含"error"、"fail"、"invalid"等关键词的行
        error_lines = [line.strip() for line in stderr_str.splitlines() if line.strip()]
        critical_errors = [
            line for line in error_lines 
            if any(keyword in line.lower() for keyword in ['error', 'fail', 'invalid', 'cannot', 'unable', 'illegal'])
        ]
        
        # 只取最后3行关键错误
        error_summary = "\n".join(critical_errors[-3:]) if critical_errors else "\n".join(error_lines[-3:])
        
        logger.error(f"{operation} 失败: {error_summary}")
        logger.debug(f"完整错误详情:\n{stderr_str}")
    else:
        logger.error(f"{operation} 发生未知异常: {e}")
        import traceback
        logger.debug(f"异常堆栈:\n{traceback.format_exc()}")


# ===== 编码器管理类 =====
class EncoderManager:
    """智能编码器管理器，记录历史成功率并优化选择"""
    
    def __init__(self, initial_encoders):
        self.encoder_stats = {}
        self.preferred_encoder = None
        
        # 初始化编码器统计
        for encoder in initial_encoders:
            encoder_name = encoder['name']
            self.encoder_stats[encoder_name] = {
                'success': 0,
                'fail': 0,
                'avg_duration': 0,
                'total_duration': 0,
                'count': 0
            }
        
        logger.info(f"初始化编码器管理器，可用编码器: {list(self.encoder_stats.keys())}")
    
    def update_success(self, encoder_name, duration):
        """更新编码器成功统计"""
        if encoder_name not in self.encoder_stats:
            logger.warning(f"未知编码器: {encoder_name}，无法更新统计")
            return
        
        stats = self.encoder_stats[encoder_name]
        stats['success'] += 1
        stats['count'] += 1
        stats['total_duration'] += duration
        stats['avg_duration'] = stats['total_duration'] / stats['count']
        
        # 设置为首选编码器
        self.preferred_encoder = encoder_name
        logger.info(f"编码器 {encoder_name} 成功，设为首选编码器，平均耗时: {format_duration(stats['avg_duration'])}")
    
    def update_failure(self, encoder_name):
        """更新编码器失败统计"""
        if encoder_name not in self.encoder_stats:
            return
        
        self.encoder_stats[encoder_name]['fail'] += 1
        logger.warning(f"编码器 {encoder_name} 失败")
    
    def get_optimal_encoder_order(self):
        """获取最优编码器顺序（基于历史成功率和速度）"""
        # 如果有首选编码器且成功次数>0，放在第一位
        encoder_order = []
        
        if self.preferred_encoder and self.encoder_stats[self.preferred_encoder]['success'] > 0:
            encoder_order.append(self.preferred_encoder)
        
        # 按成功率和速度排序的其余编码器
        remaining_encoders = [
            name for name in self.encoder_stats.keys() 
            if name != self.preferred_encoder
        ]
        
        # 计算成功率和速度得分
        encoder_scores = []
        for name in remaining_encoders:
            stats = self.encoder_stats[name]
            success_rate = stats['success'] / (stats['success'] + stats['fail'] + 1)  # +1 避免除零
            speed_score = 1 / (stats['avg_duration'] + 1) if stats['avg_duration'] > 0 else 0
            total_score = success_rate * 0.7 + speed_score * 0.3
            encoder_scores.append((name, total_score))
        
        # 按得分排序
        encoder_scores.sort(key=lambda x: x[1], reverse=True)
        encoder_order.extend([name for name, _ in encoder_scores])
        
        logger.debug(f"编码器优化顺序: {encoder_order}")
        return encoder_order
    
    def get_encoder_config(self, encoder_name):
        """获取编码器配置"""
        for config in ENCODER_PRIORITY:
            if config['name'] == encoder_name:
                return config
        return None


# ===== 进度跟踪器 =====
class ProgressTracker:
    """进度跟踪和ETA预估"""
    
    def __init__(self, total_segments):
        self.total_segments = total_segments
        self.completed = 0
        self.baseline_duration = None  # 基准时长（首个成功片段）
        self.actual_durations = []    # 实际耗时记录
        self.start_time = time.time()
        self.baseline_set = False
        logger.info(f"初始化进度跟踪器，总片段数: {total_segments}")
    
    def update_baseline(self, duration):
        """设置基准时长（首个成功片段）"""
        if self.baseline_set:
            return
        
        self.baseline_duration = duration
        self.baseline_set = True
        logger.info(f"设置基准处理时长: {format_duration(duration)}")
    
    def mark_completed(self, duration):
        """标记一个片段完成并记录耗时"""
        self.completed += 1
        self.actual_durations.append(duration)
        
        # 如果还没有基准时长，使用当前片段作为基准
        if not self.baseline_set:
            self.update_baseline(duration)
    
    def get_progress_info(self):
        """获取进度信息"""
        if self.baseline_duration is None:
            return f"{self.completed}/{self.total_segments} (无基准)"
        
        progress = self.completed / self.total_segments
        remaining_segments = self.total_segments - self.completed
        
        # 估计剩余时间
        if len(self.actual_durations) > 0:
            avg_duration = sum(self.actual_durations) / len(self.actual_durations)
            ratio = avg_duration / self.baseline_duration if self.baseline_duration > 0 else 1
            eta = self.baseline_duration * remaining_segments * ratio
        else:
            eta = self.baseline_duration * remaining_segments
        
        return {
            'completed': self.completed,
            'total': self.total_segments,
            'progress': progress,
            'eta': eta
        }
    
    def get_progress_bar(self, width=50):
        """生成可视化进度条"""
        if self.baseline_duration is None:
            progress = self.completed / self.total_segments if self.total_segments > 0 else 0
            filled = int(width * progress)
            remaining = width - filled
            return f"[视频拼接任务总进度:{'█' * filled}{'░' * remaining}] {self.completed}/{self.total_segments} ({progress:.1%})"
        
        progress_info = self.get_progress_info()
        progress = progress_info['progress']
        eta = progress_info['eta']
        
        filled = int(width * progress)
        remaining = width - filled
        
        # 格式化ETA
        eta_str = format_duration(eta) if eta > 0 else "计算中..."
        
        bar = f"[{'█' * filled}{'░' * remaining}] {self.completed}/{self.total_segments} "
        bar += f"({progress:.1%}) ETA: {eta_str}"
        return bar
    
    def get_elapsed_time(self):
        """获取已用时间"""
        return time.time() - self.start_time
    
    def get_total_estimated_time(self):
        """获取总预估时间"""
        if not self.baseline_set or self.total_segments == 0:
            return 0
        
        progress_info = self.get_progress_info()
        elapsed = self.get_elapsed_time()
        completed_ratio = self.completed / self.total_segments
        
        if completed_ratio == 0:
            return 0
        
        return elapsed / completed_ratio


# ===== 目录状态管理类 =====
class DirectoryStateManager:
    """多目录状态管理器"""
    
    def __init__(self, watch_directories):
        self.directories = {}
        self.lock = threading.RLock()
        
        # 初始化目录状态
        for dir_path, config in watch_directories.items():
            dir_path = os.path.normpath(dir_path)
            self.directories[dir_path] = {
                'config': config,
                'last_modified': 0,           # 最后修改时间戳
                'stable_since': 0,            # 稳定开始时间
                'processed_files': set(),     # 已处理文件集合
                'current_file': None,         # 当前正在处理的文件
                'status': 'pending',          # pending/processing/completed/failed
                'resolved_input': get_resolved_path(dir_path, config, 'input_dir', '剪辑'),
                'resolved_output': get_resolved_path(dir_path, config, 'output_dir', '成片'),
            }
            logger.info(f"初始化监听目录: {dir_path}")
            logger.info(f"  INPUT: {self.directories[dir_path]['resolved_input']}")
            logger.info(f"  OUTPUT: {self.directories[dir_path]['resolved_output']}")
    
    def get_pending_directories(self):
        """获取状态为pending的目录列表"""
        with self.lock:
            return [dir_path for dir_path, state in self.directories.items() 
                   if state['status'] == 'pending']
    
    def get_processing_directories(self):
        """获取正在处理的目录"""
        with self.lock:
            return [dir_path for dir_path, state in self.directories.items() 
                   if state['status'] == 'processing']
    
    def mark_directory_processing(self, dir_path, filename):
        """标记目录为处理中状态"""
        with self.lock:
            if dir_path in self.directories:
                self.directories[dir_path]['status'] = 'processing'
                self.directories[dir_path]['current_file'] = filename
                user_logger.info(f"▶ 开始处理: {os.path.basename(filename)} ({dir_path})")
    
    def mark_directory_completed(self, dir_path):
        """标记目录为完成状态"""
        with self.lock:
            if dir_path in self.directories:
                self.directories[dir_path]['status'] = 'completed'
                user_logger.info(f"✓ 目录完成: {dir_path}")
    
    def mark_file_processed(self, dir_path, filename):
        """标记文件为已处理"""
        with self.lock:
            if dir_path in self.directories:
                self.directories[dir_path]['processed_files'].add(filename)
                logger.debug(f"文件标记为已处理: {dir_path}/{filename}")
    
    def update_directory_stability(self, dir_path, is_stable):
        """更新目录稳定性状态"""
        with self.lock:
            if dir_path in self.directories:
                current_time = time.time()
                if is_stable:
                    if self.directories[dir_path]['stable_since'] == 0:
                        self.directories[dir_path]['stable_since'] = current_time
                        logger.info(f"目录开始稳定: {dir_path}")
                else:
                    self.directories[dir_path]['stable_since'] = 0
                    self.directories[dir_path]['last_modified'] = current_time
                    logger.info(f"目录有变化，重置稳定计时: {dir_path}")
    
    def is_directory_stable(self, dir_path):
        """检查目录是否稳定（达到配置的稳定时长）"""
        with self.lock:
            if dir_path not in self.directories:
                return False
            
            dir_state = self.directories[dir_path]
            stable_duration = dir_state['config']['watch_duration']
            current_time = time.time()
            
            if dir_state['stable_since'] > 0:
                stable_time = current_time - dir_state['stable_since']
                if stable_time >= stable_duration:
                    logger.info(f"目录已稳定: {dir_path} (稳定时长: {stable_time:.1f}/{stable_duration}秒)")
                    return True
            return False
    
    def all_directories_completed(self):
        """检查所有目录是否都已完成"""
        with self.lock:
            for dir_path, state in self.directories.items():
                if state['status'] not in ['completed', 'failed']:
                    return False
            return True
    
    def get_directory_status(self, dir_path):
        """获取目录当前状态"""
        with self.lock:
            return self.directories.get(dir_path, {}).get('status', 'unknown')


# ===== 任务队列管理 =====
class TaskQueue:
    """线程安全的任务队列"""
    
    def __init__(self):
        self.queue = Queue()
        self.stop_event = Event()
        self.lock = threading.RLock()
        self.active_tasks = {}  # dir_path: task_count
    
    def add_task(self, task):
        """添加任务到队列"""
        with self.lock:
            self.queue.put(task)
            dir_path = task['dir_path']
            self.active_tasks[dir_path] = self.active_tasks.get(dir_path, 0) + 1
            logger.info(f"添加新任务: {dir_path}/{task['filename']}, 队列大小: {self.queue.qsize()}")
            user_logger.info(f"📋 发现新任务: {task['filename']}")
    
    def get_task(self, timeout=5):
        """从队列获取任务"""
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None
    
    def mark_task_complete(self, task):
        """标记任务完成"""
        with self.lock:
            dir_path = task['dir_path']
            if dir_path in self.active_tasks:
                self.active_tasks[dir_path] -= 1
                if self.active_tasks[dir_path] <= 0:
                    del self.active_tasks[dir_path]
            self.queue.task_done()
    
    def should_stop(self):
        """检查是否应该停止"""
        return self.stop_event.is_set() and self.queue.empty()
    
    def stop(self):
        """请求停止"""
        self.stop_event.set()
        logger.info("任务队列收到停止请求")
    
    def get_active_task_count(self):
        """获取活跃任务数量"""
        with self.lock:
            return sum(self.active_tasks.values())


# ===== 多目录监听器 =====
class MultiDirectoryWatcher:
    """多目录监听器"""
    
    def __init__(self, directory_state_manager):
        self.state_manager = directory_state_manager
        logger.info("初始化多目录监听器")
    
    def check_directory_stability(self, dir_path):
        """检查单个目录的稳定性"""
        try:
            current_time = time.time()
            last_modified = 0
            dir_state = self.state_manager.directories[dir_path]
            scan_dir = dir_state['resolved_input']

            # 检查目录中所有MP4文件的最后修改时间
            for file in os.listdir(scan_dir):
                if file.lower().endswith('.mp4'):
                    file_path = os.path.join(scan_dir, file)
                    if os.path.exists(file_path):
                        file_mtime = os.path.getmtime(file_path)
                        if file_mtime > last_modified:
                            last_modified = file_mtime
            
            # 更新目录状态
            is_stable = (current_time - last_modified) > self.state_manager.directories[dir_path]['config']['watch_duration']
            self.state_manager.update_directory_stability(dir_path, is_stable)
            
            return is_stable
            
        except Exception as e:
            logger.error(f"检查目录稳定性时出错: {dir_path}, 错误: {e}")
            return False
    
    def find_ready_files(self, dir_path):
        """在稳定目录中查找准备好的文件"""
        try:
            dir_state = self.state_manager.directories[dir_path]
            scan_dir = dir_state['resolved_input']
            ready_files = []

            for file in os.listdir(scan_dir):
                if file.lower().endswith('.mp4') and file not in dir_state['processed_files']:
                    file_path = os.path.join(scan_dir, file)

                    # 检查文件是否就绪
                    if is_file_ready(file_path, FILE_STABLE_DURATION):
                        ready_files.append(file)
                        logger.info(f"发现就绪文件: {scan_dir}/{file}")
            
            return ready_files
            
        except Exception as e:
            logger.error(f"查找就绪文件时出错: {dir_path}, 错误: {e}")
            return []


# ===== 监听线程 =====
class WatcherThread(threading.Thread):
    """专用监听线程"""
    
    def __init__(self, dir_state_manager, task_queue, watch_interval=WATCHER_THREAD_INTERVAL):
        super().__init__(daemon=True)
        self.dir_state_manager = dir_state_manager
        self.task_queue = task_queue
        self.watch_interval = watch_interval
        self.watcher = MultiDirectoryWatcher(dir_state_manager)
        logger.info(f"初始化监听线程，轮询间隔: {watch_interval}秒")
    
    def run(self):
        """监听线程主循环"""
        logger.info("监听线程启动")
        try:
            while not self.task_queue.should_stop():
                # 轮询所有pending目录
                pending_dirs = self.dir_state_manager.get_pending_directories()
                
                for dir_path in pending_dirs:
                    # 检查目录稳定性
                    self.watcher.check_directory_stability(dir_path)

                    # 如果目录稳定，查找就绪文件
                    if self.dir_state_manager.is_directory_stable(dir_path):
                        ready_files = self.watcher.find_ready_files(dir_path)
                        for filename in ready_files:
                            # 获取目录级片头片尾配置（优先）或全局配置
                            start_video, end_video = get_directory_intro_ending(dir_path)

                            # 获取解析后的输入输出目录
                            dir_state = self.dir_state_manager.directories[dir_path]

                            # 创建任务
                            task = {
                                'dir_path': dir_path,
                                'input_dir': dir_state['resolved_input'],
                                'output_dir': dir_state['resolved_output'],
                                'filename': filename,
                                'start_video': start_video,
                                'end_video': end_video,
                                'added_time': time.time(),
                                'status': 'pending'
                            }
                            self.task_queue.add_task(task)
                            self.dir_state_manager.mark_directory_processing(dir_path, filename)
                
                # 短暂休眠，避免CPU过载
                time.sleep(self.watch_interval)
                
        except Exception as e:
            logger.error(f"监听线程异常: {e}")
        finally:
            logger.info("监听线程退出")


# ===== 元数据管理类 =====
class ProcessingMetadata:
    """视频处理元数据管理"""
    
    def __init__(self, metadata_file=METADATA_FILE):
        self.metadata_file = metadata_file
        self.metadata = self._load_metadata()
        self.lock = threading.RLock()
        logger.info(f"初始化元数据管理器，使用可重入锁")
    
    def _load_metadata(self):
        """加载元数据文件"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                logger.info(f"已加载元数据文件: {self.metadata_file}")
                return metadata
            except Exception as e:
                logger.error(f"加载元数据文件失败: {e}，将创建新文件")
        
        return {
            "program_start_time": get_current_time(),
            "processed_videos": {},
            "pending_videos": [],
            "encoder_usage_stats": {},
            "program_status": "running"
        }
    
    def save_metadata(self):
        """保存元数据到文件（调用者必须已持有 self.lock）"""
        try:
            logger.debug("开始保存元数据文件...")
            meta_dir = os.path.dirname(self.metadata_file)
            if meta_dir:
                os.makedirs(meta_dir, exist_ok=True)
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)
            logger.debug("元数据文件已保存")
        except Exception as e:
            logger.error(f"保存元数据文件失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
    
    def add_video(self, video_path, total_duration, dir_key=None, output_dir=None):
        """添加新视频到元数据"""
        video_name = os.path.basename(video_path)
        with self.lock:
            if video_name not in self.metadata["processed_videos"]:
                self.metadata["processed_videos"][video_name] = {
                    "original_path": video_path,
                    "total_duration": total_duration,
                    "dir_key": dir_key or os.path.dirname(video_path),
                    "output_dir": output_dir or os.path.dirname(video_path),
                    "process_start_time": get_current_time(),
                    "process_end_time": None,
                    "status": "processing",
                    "segments": []
                }
                logger.info(f"已添加视频到元数据: {video_name}")
            self.save_metadata()
        
    def add_segment(self, video_name, segment_file, start_time, end_time, actual_duration):
        """添加分割片段信息"""
        with self.lock:
            if video_name in self.metadata["processed_videos"]:
                segment_info = {
                    "segment_file": segment_file,
                    "start_time": start_time,
                    "end_time": end_time,
                    "actual_duration": actual_duration,
                    "concatenated_result": None,
                    "concatenate_start_time": None,
                    "concatenate_end_time": None,
                    "status": "pending",
                    "encoder_used": None,
                    "error_message": None,
                    "retry_count": 0  # 重试次数
                }
                self.metadata["processed_videos"][video_name]["segments"].append(segment_info)
                logger.info(f"已添加分割片段: {segment_file}")
            self.save_metadata()

    def update_segment_concatenation(self, video_name, segment_index, result_path, encoder_used, success=True, error_message=None):
        """更新片段拼接状态"""
        with self.lock:
            try:
                video_data = self.metadata["processed_videos"][video_name]
                segment = video_data["segments"][segment_index]
                
                # 确保retry_count字段存在
                if "retry_count" not in segment:
                    segment["retry_count"] = 0
                
                if success:
                    segment["status"] = "success"
                    segment["concatenated_result"] = result_path
                    segment["concatenate_end_time"] = get_current_time()
                    segment["encoder_used"] = encoder_used
                    user_logger.info(f"✓ 片段 {segment_index+1} 拼接成功")
                else:
                    segment["retry_count"] += 1
                    if segment["retry_count"] >= MAX_RETRY_COUNT:
                        segment["status"] = "failed_permanent"
                        user_logger.error(f"✗ 片段 {segment_index+1} 永久失败 (已重试 {MAX_RETRY_COUNT} 次)")
                    else:
                        segment["status"] = "failed"
                        user_logger.warning(f"⚠ 片段 {segment_index+1} 失败，重试次数: {segment['retry_count']}/{MAX_RETRY_COUNT}")
                    
                    segment["error_message"] = str(error_message)
                    segment["concatenate_end_time"] = get_current_time()
                    logger.error(f"更新片段拼接状态: {segment_index} -> 失败: {error_message}")
                
                if encoder_used:
                    if encoder_used not in self.metadata["encoder_usage_stats"]:
                        self.metadata["encoder_usage_stats"][encoder_used] = 0
                    self.metadata["encoder_usage_stats"][encoder_used] += 1
                
                self.save_metadata()
                return True
            except (KeyError, IndexError) as e:
                logger.error(f"更新片段状态失败: {e}")
                return False
    
    def update_video_status(self, video_name, status):
        """更新视频处理状态"""
        with self.lock:
            if video_name in self.metadata["processed_videos"]:
                self.metadata["processed_videos"][video_name]["status"] = status
                self.metadata["processed_videos"][video_name]["process_end_time"] = get_current_time()
                if status == "completed":
                    user_logger.info(f"✓ 视频处理完成: {video_name}")
                elif status == "failed":
                    user_logger.error(f"✗ 视频处理失败: {video_name}")
                logger.info(f"更新视频状态: {video_name} -> {status}")
            self.save_metadata()
    
    def get_pending_segments(self):
        """获取所有待处理的片段"""
        pending_segments = []
        with self.lock:
            for video_name, video_data in self.metadata["processed_videos"].items():
                for idx, segment in enumerate(video_data["segments"]):
                    # 确保retry_count字段存在
                    if "retry_count" not in segment:
                        segment["retry_count"] = 0
                        
                    if segment["status"] in ["pending", "failed"] and segment["retry_count"] < MAX_RETRY_COUNT:
                        pending_segments.append({
                            "video_name": video_name,
                            "segment_index": idx,
                            "segment_info": segment,
                            "video_info": video_data
                        })
        return pending_segments
    
    def all_tasks_completed(self):
        """检查所有任务是否完成"""
        with self.lock:
            for video_name, video_data in self.metadata["processed_videos"].items():
                if video_data["status"] == "processing":
                    return False
                for segment in video_data["segments"]:
                    # 确保retry_count字段存在
                    if "retry_count" not in segment:
                        segment["retry_count"] = 0
                        
                    if segment["status"] in ["pending", "processing", "failed"] and segment["retry_count"] < MAX_RETRY_COUNT:
                        return False
            return True
    
    def mark_program_completed(self):
        """标记程序完成"""
        with self.lock:
            self.metadata["program_status"] = "completed"
            self.metadata["program_end_time"] = get_current_time()
            self.save_metadata()


# ===== 验证输入文件 =====
def validate_input_files():
    """验证配置的文件是否存在且为有效文件（不是目录）"""
    errors = []
    config_summary = []
    
    need_global_start = False
    need_global_end = False
    
    for dir_path, config in WATCH_DIRECTORIES.items():
        dir_name = os.path.basename(dir_path)
        start_source = ""
        end_source = ""
        
        dir_start = config.get('start_video')
        if dir_start:
            if os.path.exists(dir_start) and os.path.isfile(dir_start):
                start_source = "目录级"
            else:
                errors.append(f"[{dir_name}] 片头文件不存在: {dir_start}")
                start_source = "❌错误"
        else:
            need_global_start = True
            start_source = "全局"
        
        dir_end = config.get('end_video')
        if dir_end:
            if os.path.exists(dir_end) and os.path.isfile(dir_end):
                end_source = "目录级"
            else:
                errors.append(f"[{dir_name}] 片尾文件不存在: {dir_end}")
                end_source = "❌错误"
        else:
            need_global_end = True
            end_source = "全局"
        
        config_summary.append({
            'dir': dir_name,
            'start': start_source,
            'end': end_source
        })
    
    if need_global_start:
        if not os.path.exists(START_VIDEO):
            errors.append(f"全局片头文件不存在: {START_VIDEO}")
        elif not os.path.isfile(START_VIDEO):
            errors.append(f"全局片头路径是目录而非文件: {START_VIDEO}")
    
    if need_global_end:
        if not os.path.exists(END_VIDEO):
            errors.append(f"全局片尾文件不存在: {END_VIDEO}")
        elif not os.path.isfile(END_VIDEO):
            errors.append(f"全局片尾路径是目录而非文件: {END_VIDEO}")
    
    for cmd in ['ffmpeg', 'ffprobe']:
        try:
            subprocess.run([cmd, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            errors.append(f"命令行工具 {cmd} 不可用 (请确保已安装并添加到PATH)")
    
    if errors:
        return errors
    
    logger.info("")
    logger.info("=" * 50)
    logger.info("✓ 配置校验通过，开始视频处理")
    for item in config_summary:
        logger.info(f"  [{item['dir']}] 片头: {item['start']:<6} | 片尾: {item['end']}")
    logger.info("=" * 50)
    logger.info("")
    
    return []


# ===== 视频处理核心函数 =====
def split_video_fast(input_video, output_dir, metadata_manager, video_name,
                     dir_key=None, resolved_output=None):
    """快速分割视频（流复制方式）"""
    start_time = time.time()
    logger.info(f"开始快速分割视频: {input_video}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    logger.info(f"创建输出目录: {output_dir}")

    total_duration = get_video_duration(input_video)
    if total_duration == 0:
        logger.error(f"无法获取视频时长，跳过处理: {input_video}")
        return []

    metadata_manager.add_video(input_video, total_duration, dir_key=dir_key, output_dir=resolved_output)
    
    num_segments = math.ceil(total_duration / SEGMENT_DURATION)
    segments = []
    
    user_logger.info(f"⌛ 分割视频: {video_name} (总时长: {format_duration(total_duration)})")
    logger.info(f"视频总时长: {total_duration:.2f}秒, 将分割为 {num_segments} 个片段")
    
    for i in range(num_segments):
        log_separator(f"分割片段 {i+1}/{num_segments}", level="segment")
        
        segment_start_time = time.time()
        start_time_pos = i * SEGMENT_DURATION
        
        if i == num_segments - 1:
            duration = total_duration - start_time_pos
        else:
            duration = SEGMENT_DURATION
        
        output_file = os.path.join(output_dir, f"segment_{i+1:03d}.mp4")
        logger.info(f"开始分割第 {i+1}/{num_segments} 段: {output_file}")
        
        cmd = [
            'ffmpeg',
            '-ss', str(start_time_pos),
            '-i', input_video,
            '-t', str(duration),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            '-y',
            output_file
        ]
        
        logger.debug(f"执行FFmpeg命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd, 
                check=True, 
                stderr=subprocess.PIPE, 
                stdout=subprocess.PIPE,
                timeout=300
            )
            
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                logger.info(f"分割片段创建成功: {output_file} ({file_size} bytes)")
                
                actual_duration = get_video_duration(output_file)
                end_time_pos = start_time_pos + actual_duration
                
                if i < num_segments - 1:
                    if not validate_segment_duration(output_file, actual_duration):
                        logger.warning(f"片段 {i+1} 时长超出允许范围: {actual_duration}秒")
                
                metadata_manager.add_segment(
                    video_name, 
                    output_file, 
                    start_time_pos, 
                    end_time_pos, 
                    actual_duration
                )
                
                segments.append(output_file)
                segment_end_time = time.time()
                logger.info(f"完成分割第 {i+1} 段，耗时: {format_duration(segment_end_time - segment_start_time)}")
            else:
                logger.error(f"分割片段文件未创建: {output_file}")
                continue
            
        except Exception as e:
            log_ffmpeg_error(e, f"分割第 {i+1} 段")
            metadata_manager.update_video_status(video_name, "failed")
            return []
    
    total_end_time = time.time()
    logger.info(f"视频分割完成，总耗时: {format_duration(total_end_time - start_time)}")
    return segments

def validate_segment_duration(segment_path, actual_duration=None):
    """验证分割片段时长是否在允许范围内"""
    if actual_duration is None:
        actual_duration = get_video_duration(segment_path)
    
    min_duration = SEGMENT_DURATION - DURATION_TOLERANCE
    max_duration = SEGMENT_DURATION + DURATION_TOLERANCE
    
    is_valid = min_duration <= actual_duration <= max_duration
    if not is_valid:
        logger.warning(f"片段时长验证失败: {actual_duration}秒 (允许范围: {min_duration}-{max_duration}秒)")
    
    return is_valid


# ===== 并行处理管理器 =====
class ParallelProcessor:
    """并行处理器"""
    
    def __init__(self, metadata_manager, encoder_manager, max_concurrent=MAX_CONCURRENT_CONCAT):
        self.metadata_manager = metadata_manager
        self.encoder_manager = encoder_manager
        self.max_concurrent = max_concurrent
        logger.info(f"初始化并行处理器，最大并发数: {max_concurrent}")
        logger.info(f"可用编码器: {[enc for enc in self.encoder_manager.encoder_stats.keys()]}")
    
    def concatenate_segment(self, segment_data, progress_tracker=None):
        """拼接单个片段（供线程池调用）"""
        video_name = segment_data["video_name"]
        segment_index = segment_data["segment_index"]
        segment_info = segment_data["segment_info"]
        video_info = segment_data["video_info"]
        
        logger.info("")
        log_separator(f"拼接片段 {segment_index+1} - {video_name}", level="segment")
        
        segment_file = segment_info["segment_file"]
        
        # 使用元数据中存储的 dir_key（合集级 key）获取片头片尾配置
        dir_key = video_info.get("dir_key", os.path.dirname(video_info["original_path"]))
        target_base = video_info.get("output_dir", os.path.dirname(video_info["original_path"]))
        start_video, end_video = get_directory_intro_ending(dir_key)
        target_dir = os.path.join(target_base, "target")
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        
        output_filename = f"{Path(video_name).stem}_c{segment_index+1}.mp4"
        output_file = os.path.join(target_dir, output_filename)
        
        logger.info(f"开始拼接片段: {segment_file} -> {output_file}")
        concatenate_start_time = time.time()
        
        # 更新元数据：标记片段为"处理中"（不经过 success=False 分支，避免误报失败）
        with self.metadata_manager.lock:
            try:
                seg = self.metadata_manager.metadata["processed_videos"][video_name]["segments"][segment_index]
                seg["status"] = "processing"
                seg["concatenate_start_time"] = get_current_time()
                self.metadata_manager.save_metadata()
            except (KeyError, IndexError):
                pass
        
        success = False
        used_encoder = None
        encoder_duration = 0
        
        # 获取优化的编码器顺序
        encoder_order = self.encoder_manager.get_optimal_encoder_order()
        
        for encoder_name in encoder_order:
            encoder_config = self.encoder_manager.get_encoder_config(encoder_name)
            if not encoder_config:
                continue
                
            logger.info(f"尝试使用编码器: {encoder_name}")
            used_encoder = encoder_name
            encoder_start_time = time.time()
            
            try:
                success = self._concatenate_with_encoder(
                    start_video, segment_file, end_video, output_file, encoder_config
                )
                encoder_duration = time.time() - encoder_start_time
                
                if success:
                    self.encoder_manager.update_success(encoder_name, encoder_duration)
                    break
                else:
                    self.encoder_manager.update_failure(encoder_name)
                    logger.warning(f"编码器 {encoder_name} 失败，尝试下一个")
            except Exception as e:
                self.encoder_manager.update_failure(encoder_name)
                logger.error(f"编码器 {encoder_name} 异常: {e}")
                continue
        
        concatenate_end_time = time.time()
        process_duration = concatenate_end_time - concatenate_start_time
        
        if success:
            logger.info(f"拼接成功: {output_file}, 使用编码器: {used_encoder}, 耗时: {format_duration(process_duration)}")
            self.metadata_manager.update_segment_concatenation(
                video_name, segment_index, output_file, used_encoder, success=True
            )
            self._cleanup_segment_file(segment_file)
            
            # 更新进度
            if progress_tracker:
                progress_tracker.mark_completed(process_duration)
                user_logger.info(progress_tracker.get_progress_bar())
            
            return True
        else:
            logger.error(f"所有可用编码器都失败: {output_file}, 耗时: {format_duration(process_duration)}")
            self.metadata_manager.update_segment_concatenation(
                video_name, segment_index, None, "所有编码器失败",
                success=False, error_message="所有编码器尝试均失败"
            )
            
            return False
    
    def _concatenate_with_encoder(self, start_video, main_segment, end_video, output_file, encoder_config):
        """使用指定编码器拼接三个视频"""
        logger.debug(f"=== 使用编码器 {encoder_config['name']} 拼接 ===")
        
        cmd = [
            'ffmpeg',
            '-y',
            '-i', start_video,
            '-i', main_segment,
            '-i', end_video,
            '-filter_complex', 
            '[0:v]setsar=1[v0];[0:a]aresample=async=1:first_pts=0[a0];'
            '[1:v]setsar=1[v1];[1:a]aresample=async=1:first_pts=0[a1];'
            '[2:v]setsar=1[v2];[2:a]aresample=async=1:first_pts=0[a2];'
            '[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]',
            '-map', '[vout]',
            '-map', '[aout]',
            '-c:v', encoder_config['name'],
            encoder_config['quality_param'], encoder_config['quality_value'],
            '-preset', encoder_config['preset'],
            '-c:a', VIDEO_PARAMS['audio_codec'],
            '-b:a', VIDEO_PARAMS['audio_bitrate'],
            '-r', VIDEO_PARAMS['framerate'],
            '-s', VIDEO_PARAMS['resolution'],
            '-pix_fmt', VIDEO_PARAMS['pix_fmt'],
            '-color_primaries', VIDEO_PARAMS['color_primaries'],
            '-color_trc', VIDEO_PARAMS['color_trc'],
            '-colorspace', VIDEO_PARAMS['colorspace'],
            '-movflags', '+faststart'
        ]
        
        if encoder_config['name'] == 'h264_nvenc':
            cmd.extend([
                '-gpu', '0',
                '-spatial_aq', '1',
                '-temporal_aq', '1'
            ])
        
        cmd.extend(encoder_config['extra_args'])
        cmd.append(output_file)
        
        logger.debug(f"执行拼接命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd, 
                check=True, 
                stderr=subprocess.PIPE, 
                stdout=subprocess.PIPE,
                timeout=600
            )
            return True
        except Exception as e:
            log_ffmpeg_error(e, f"拼接片段（编码器 {encoder_config['name']}）")
            return False

    def _cleanup_segment_file(self, segment_path):
        """清理分割片段文件 - 仅在成功时清理"""
        try:
            if os.path.exists(segment_path):
                os.remove(segment_path)
                logger.info(f"已清理分割片段: {segment_path}")
                return True
            else:
                logger.warning(f"分割片段不存在，无需清理: {segment_path}")
                return False
        except Exception as e:
            logger.error(f"清理分割片段时出错: {segment_path}, 错误: {e}")
            return False
        
    def process_all_pending_segments(self):
        """处理所有待处理的片段"""
        pending_segments = self.metadata_manager.get_pending_segments()
        
        if not pending_segments:
            logger.debug("没有待处理的片段")
            return
        
        total_segments = len(pending_segments)
        progress_tracker = ProgressTracker(total_segments)
        
        user_logger.info(f"🎬 开始拼接 {total_segments} 个片段")
        logger.info(f"开始并行处理 {len(pending_segments)} 个待处理片段")
        
        completed_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            future_to_segment = {
                executor.submit(self.concatenate_segment, segment, progress_tracker): segment 
                for segment in pending_segments
            }
            
            for future in as_completed(future_to_segment):
                segment_data = future_to_segment[future]
                segment_index = segment_data["segment_index"]
                try:
                    result = future.result()
                    completed_count += 1
                except Exception as e:
                    logger.error(f"处理片段时发生异常: {e}")
                    completed_count += 1
        
        logger.info(f"所有片段处理完成: {completed_count}/{total_segments}")
        
        # 显示最终统计
        elapsed = progress_tracker.get_elapsed_time()
        estimated = progress_tracker.get_total_estimated_time()
        user_logger.info(f"⏱️  总耗时: {format_duration(elapsed)}, 预估总耗时: {format_duration(estimated)}")
        
        # 打印编码器统计
        encoder_stats = self.encoder_manager.encoder_stats
        user_logger.info("📊 编码器使用统计:")
        for name, stats in encoder_stats.items():
            success_rate = stats['success'] / (stats['success'] + stats['fail']) if (stats['success'] + stats['fail']) > 0 else 0
            avg_duration = stats['avg_duration'] if stats['count'] > 0 else 0
            user_logger.info(f"  - {name}: 成功率 {success_rate:.1%}, 平均耗时 {format_duration(avg_duration)}")


# ===== 处理线程池 =====
class ProcessorPool:
    """处理线程池"""
    
    def __init__(self, task_queue, metadata_manager, encoder_manager, max_workers=PROCESSOR_THREADS):
        self.task_queue = task_queue
        self.metadata_manager = metadata_manager
        self.encoder_manager = encoder_manager
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.futures = []
        self.stop_event = Event()
        logger.info(f"初始化处理线程池，最大工作线程: {max_workers}")
    
    def start(self):
        """启动处理线程池"""
        for i in range(self.max_workers):
            future = self.executor.submit(self.worker_loop, i+1)
            self.futures.append(future)
        logger.info("处理线程池已启动")
    
    def worker_loop(self, worker_id):
        """工作线程主循环"""
        logger.info(f"处理工作线程 {worker_id} 启动")
        
        while not (self.task_queue.should_stop() or self.stop_event.is_set()):
            task = self.task_queue.get_task(timeout=10)
            
            if task:
                try:
                    logger.info(f"工作线程 {worker_id} 获取任务: {task['dir_path']}/{task['filename']}")
                    self.process_task(task, worker_id)
                except Exception as e:
                    logger.error(f"工作线程 {worker_id} 处理任务失败: {e}")
                finally:
                    self.task_queue.mark_task_complete(task)
        
        logger.info(f"工作线程 {worker_id} 退出")
    
    def process_task(self, task, worker_id):
        """处理单个任务"""
        dir_path = task['dir_path']
        input_dir = task.get('input_dir', dir_path)
        output_dir = task.get('output_dir', dir_path)
        filename = task['filename']

        try:
            # 1. 快速分割
            full_path = os.path.join(input_dir, filename)
            stem = Path(filename).stem
            cut_dir = os.path.join(output_dir, "cut", stem)

            video_name = os.path.basename(full_path)
            log_separator(f"开始处理视频: {video_name}", level="main")
            log_separator("视频分割阶段", level="sub")

            segments = split_video_fast(full_path, cut_dir, self.metadata_manager, video_name,
                                         dir_key=dir_path, resolved_output=output_dir)
            
            if not segments:
                logger.error(f"工作线程 {worker_id} 分割失败: {dir_path}/{filename}")
                self.metadata_manager.update_video_status(video_name, "failed")
                return False
                
            log_separator(f"完成处理视频: {video_name}", level="main")
            return True
                
        except Exception as e:
            logger.error(f"工作线程 {worker_id} 处理异常: {dir_path}/{filename}, 错误: {e}")
            return False
    
    def stop(self, timeout=60):
        """停止处理线程池"""
        self.stop_event.set()
        logger.info("请求停止处理线程池")
        
        # 等待所有工作线程完成
        try:
            wait(self.futures, timeout=timeout)
            logger.info("所有工作线程已停止")
        except Exception as e:
            logger.error(f"等待工作线程停止时出错: {e}")
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        logger.info("处理线程池已关闭")


# ===== 编码器初始化 =====
def get_available_encoders():
    """获取所有可用的编码器"""
    try:
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-encoders']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        available_encoders = []
        
        for encoder_config in ENCODER_PRIORITY:
            encoder_name = encoder_config['name']
            if encoder_name in result.stdout:
                available_encoders.append(encoder_config)
                logger.info(f"编码器可用: {encoder_name}")
            else:
                logger.warning(f"编码器不可用: {encoder_name}")
        
        if not available_encoders:
            logger.error("没有可用的编码器，程序无法继续")
            return []
        
        return available_encoders
    except Exception as e:
        logger.error(f"检查编码器时出错: {e}")
        return []


# ===== 主程序 =====
def main():
    """主程序 - 线程化架构"""
    script_start_time = time.time()
    log_separator("程序启动", level="main")
    log_separator(f"启动时间: {get_current_time()}", level="sub")
    
    # 记录FFmpeg版本信息（只需一次）
    log_ffmpeg_version()
    
    # 验证输入文件
    validation_errors = validate_input_files()
    if validation_errors:
        user_logger.error("✗ 配置错误，以下问题需要修复:")
        for error in validation_errors:
            user_logger.error(f"  - {error}")
        user_logger.error("程序终止，请修复配置后重新运行")
        return
    
    # 确保所有目录的子目录存在（使用解析后的输出路径）
    for dir_path, config in WATCH_DIRECTORIES.items():
        dir_path = os.path.normpath(dir_path)
        resolved_out = get_resolved_path(dir_path, config, 'output_dir', '成片')
        cut_dir = os.path.join(resolved_out, "cut")
        target_dir = os.path.join(resolved_out, "target")
        Path(cut_dir).mkdir(parents=True, exist_ok=True)
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"确保目录存在: {dir_path}")
        logger.info(f"  CUT_DIR: {cut_dir}")
        logger.info(f"  TARGET_DIR: {target_dir}")
    
    # 初始化核心组件
    dir_state_manager = DirectoryStateManager(WATCH_DIRECTORIES)
    metadata_manager = ProcessingMetadata()
    
    # 初始化编码器
    user_logger.info("🔧 检测可用编码器...")
    available_encoders = get_available_encoders()
    if not available_encoders:
        user_logger.error("✗ 没有可用的编码器，程序无法继续")
        return
    
    # 创建编码器管理器
    encoder_manager = EncoderManager(available_encoders)
    
    task_queue = TaskQueue()
    
    # 创建并启动线程
    watcher_thread = WatcherThread(dir_state_manager, task_queue)
    processor_pool = ProcessorPool(task_queue, metadata_manager, encoder_manager)
    
    watcher_thread.start()
    processor_pool.start()
    
    user_logger.info("🚀 所有线程已启动，开始监控目录")
    logger.info("所有线程已启动，进入主监控循环")
    
    try:
        # 主循环：专注于全局状态和片段拼接
        last_progress_log = 0
        progress_log_interval = 10  # 10秒记录一次进度
        
        while not (task_queue.should_stop() and dir_state_manager.all_directories_completed()):
            # 检查待拼接片段（全局视角）
            pending_segments = metadata_manager.get_pending_segments()
            
            current_time = time.time()
            if pending_segments and (current_time - last_progress_log > progress_log_interval):
                total_segments = len(pending_segments)
                user_logger.info(f"⏳ 等待拼接的片段: {total_segments} 个")
                last_progress_log = current_time
            
            if pending_segments:
                logger.info(f"检测到 {len(pending_segments)} 个待拼接片段")
                log_separator("片段拼接阶段", level="sub")
                # 使用现有拼接逻辑，但限制并发
                processor = ParallelProcessor(metadata_manager, encoder_manager)
                processor.process_all_pending_segments()
            
            # 检查系统状态
            if dir_state_manager.all_directories_completed():
                logger.info("所有目录处理完成，请求停止")
                task_queue.stop()
            
            time.sleep(3)  # 主循环间隔
    
    except KeyboardInterrupt:
        user_logger.info("\n🛑 收到中断信号，请求优雅停止...")
        logger.info("收到中断信号，请求优雅停止...")
        task_queue.stop()
    except Exception as e:
        user_logger.error(f"✗ 主循环异常: {e}")
        logger.error(f"主循环异常: {e}")
        task_queue.stop()
    finally:
        # 优雅关闭
        user_logger.info("CloseOperation 优雅关闭流程...")
        logger.info("开始优雅关闭流程...")
        
        # 1. 停止任务队列
        task_queue.stop()
        
        # 2. 停止处理线程池
        processor_pool.stop(timeout=60)
        
        # 3. 等待监听线程
        if watcher_thread.is_alive():
            logger.info("等待监听线程完成...")
            watcher_thread.join(timeout=10)
        
        # 4. 最终状态检查
        if dir_state_manager.all_directories_completed():
            logger.info("所有目录处理完成")
        else:
            uncompleted_dirs = [d for d, s in dir_state_manager.directories.items() 
                              if s['status'] not in ['completed', 'failed']]
            logger.warning(f"{len(uncompleted_dirs)} 个目录未完成处理")
        
        # 5. 保存最终元数据
        metadata_manager.mark_program_completed()
        
        # 6. 计算总耗时
        total_duration = time.time() - script_start_time
        
        log_separator("程序结束", level="main")
        log_separator(f"总耗时: {format_duration(total_duration)}", level="sub")
        user_logger.info(f"✅ 程序执行完成，总耗时: {format_duration(total_duration)}")

# ===== 程序入口 =====
if __name__ == "__main__":
    main()