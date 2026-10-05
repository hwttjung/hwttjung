import logging
import os
import sys

def get_domain_logger(domain_name):
    if not domain_name:
        domain_name = "general"
        
    logger = logging.getLogger(domain_name)
    
    # 이미 핸들러가 등록되어 있다면 그대로 반환
    if logger.hasHandlers():
        return logger
        
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    os.makedirs("logs", exist_ok=True)
    
    formatter = logging.Formatter('%(asctime)s - [%(name)s] - %(levelname)s - %(message)s')
    
    fh = logging.FileHandler(f"logs/{domain_name}.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    return logger
