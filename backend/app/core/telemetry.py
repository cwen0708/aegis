import psutil
import time
from typing import Dict, Any

def get_system_metrics() -> Dict[str, Any]:
    """收集系統資源使用狀況"""
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_available_gb": round(psutil.virtual_memory().available / (1024 ** 3), 2),
        "disk_percent": psutil.disk_usage('/').percent,
        "timestamp": time.time()
    }

def is_system_overloaded(cpu_threshold=90.0, mem_threshold=90.0) -> bool:
    """判斷系統是否超過安全負載，以決定是否暫停派發新任務"""
    metrics = get_system_metrics()
    return metrics["cpu_percent"] >= cpu_threshold or metrics["memory_percent"] >= mem_threshold
