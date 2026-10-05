from __future__ import annotations
import os
import json
import fcntl
from datetime import datetime, timezone, timedelta

class CostTracker:
    """
    API 호출 횟수 및 비용 실시간 추적기 & 유료 과금 방어선 (Budget Guard)
    - Google Custom Search JSON API 일일 100건 무료 한도 자동 모니터링 & 과금 차단
    - Gemini Multimodal API 토큰 및 예상 비용(USD/KRW) 실시간 누적
    """
    
    TRACKER_FILE = "data/api_cost_tracker.json"
    
    # 2026년 기준 모델별 단가 (Gemini 3.1 Flash-Lite / 2.5 Flash)
    PRICE_PER_1M_INPUT_TOKENS_USD = 0.075
    PRICE_PER_1M_OUTPUT_TOKENS_USD = 0.30
    USD_TO_KRW_RATE = 1350.0  # 고정 환산 기준 환율
    
    def __init__(self, tracker_path: str = None):
        self.tracker_path = tracker_path or self.TRACKER_FILE
        os.makedirs(os.path.dirname(self.tracker_path), exist_ok=True)
        
    def _lock(self):
        lock_file = self.tracker_path + ".lock"
        return _FileLock(lock_file)
        
    def _get_kst_date(self) -> str:
        kst = timezone(timedelta(hours=9))
        return datetime.now(kst).strftime("%Y-%m-%d")
        
    def _get_kst_month(self) -> str:
        kst = timezone(timedelta(hours=9))
        return datetime.now(kst).strftime("%Y-%m")
        
    def _load_data(self) -> dict:
        if not os.path.exists(self.tracker_path):
            return {"daily": {}, "monthly": {}}
        try:
            with open(self.tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"daily": {}, "monthly": {}}
            
    def _save_data(self, data: dict):
        temp_path = self.tracker_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.tracker_path)
        
    def can_use_google_cse(self, max_free_limit: int = 100, allow_paid: bool = False) -> bool:
        """
        오늘 Google CSE를 무료 한도 내에서 안전하게 호출할 수 있는지 검사
        - allow_paid가 False(기본)인 경우, 100회 도달 시 즉시 False 반환 (유료 과금 원천 방어)
        """
        if allow_paid:
            return True
            
        today = self._get_kst_date()
        with self._lock():
            data = self._load_data()
            daily_stats = data.get("daily", {}).get(today, {})
            current_calls = daily_stats.get("google_cse_calls", 0)
            return current_calls < max_free_limit
            
    def record_google_cse_call(self, count: int = 1):
        """Google CSE 호출 카운트 기록"""
        today = self._get_kst_date()
        month = self._get_kst_month()
        
        with self._lock():
            data = self._load_data()
            
            # Daily
            if today not in data["daily"]:
                data["daily"][today] = self._empty_daily_record()
            data["daily"][today]["google_cse_calls"] += count
            
            # Monthly
            if month not in data["monthly"]:
                data["monthly"][month] = self._empty_monthly_record()
            data["monthly"][month]["google_cse_calls"] += count
            
            self._save_data(data)
            
    def record_unsplash_call(self, count: int = 1):
        """Unsplash 호출 카운트 기록 (무료)"""
        today = self._get_kst_date()
        month = self._get_kst_month()
        with self._lock():
            data = self._load_data()
            if today not in data["daily"]:
                data["daily"][today] = self._empty_daily_record()
            data["daily"][today]["unsplash_calls"] += count
            
            if month not in data["monthly"]:
                data["monthly"][month] = self._empty_monthly_record()
            data["monthly"][month]["unsplash_calls"] += count
            self._save_data(data)
            
    def record_pexels_call(self, count: int = 1):
        """Pexels 호출 카운트 기록 (무료)"""
        today = self._get_kst_date()
        month = self._get_kst_month()
        with self._lock():
            data = self._load_data()
            if today not in data["daily"]:
                data["daily"][today] = self._empty_daily_record()
            data["daily"][today]["pexels_calls"] += count
            
            if month not in data["monthly"]:
                data["monthly"][month] = self._empty_monthly_record()
            data["monthly"][month]["pexels_calls"] += count
            self._save_data(data)
            
    def record_gemini_multimodal_call(self, input_tokens: int, output_tokens: int):
        """Gemini 멀티모달 API 호출 토큰 및 비용 기록"""
        today = self._get_kst_date()
        month = self._get_kst_month()
        
        input_cost = (input_tokens / 1_000_000) * self.PRICE_PER_1M_INPUT_TOKENS_USD
        output_cost = (output_tokens / 1_000_000) * self.PRICE_PER_1M_OUTPUT_TOKENS_USD
        call_cost_usd = input_cost + output_cost
        call_cost_krw = call_cost_usd * self.USD_TO_KRW_RATE
        
        with self._lock():
            data = self._load_data()
            
            # Daily
            if today not in data["daily"]:
                data["daily"][today] = self._empty_daily_record()
            rec = data["daily"][today]
            rec["gemini_multimodal_calls"] += 1
            rec["gemini_input_tokens"] += input_tokens
            rec["gemini_output_tokens"] += output_tokens
            rec["estimated_cost_usd"] = round(rec.get("estimated_cost_usd", 0.0) + call_cost_usd, 6)
            rec["estimated_cost_krw"] = round(rec.get("estimated_cost_krw", 0.0) + call_cost_krw, 2)
            
            # Monthly
            if month not in data["monthly"]:
                data["monthly"][month] = self._empty_monthly_record()
            m_rec = data["monthly"][month]
            m_rec["gemini_multimodal_calls"] += 1
            m_rec["gemini_tokens"] += (input_tokens + output_tokens)
            m_rec["estimated_cost_usd"] = round(m_rec.get("estimated_cost_usd", 0.0) + call_cost_usd, 4)
            m_rec["estimated_cost_krw"] = round(m_rec.get("estimated_cost_krw", 0.0) + call_cost_krw, 2)
            
            self._save_data(data)
            
    def get_daily_summary(self, date_str: str = None) -> dict:
        """지정 날짜(또는 오늘)의 사용량 및 비용 요약 반환"""
        date_key = date_str or self._get_kst_date()
        with self._lock():
            data = self._load_data()
            return data.get("daily", {}).get(date_key, self._empty_daily_record())
            
    def get_monthly_summary(self, month_str: str = None) -> dict:
        """지정 월(또는 당월)의 사용량 및 비용 요약 반환"""
        month_key = month_str or self._get_kst_month()
        with self._lock():
            data = self._load_data()
            return data.get("monthly", {}).get(month_key, self._empty_monthly_record())
            
    def format_telegram_report(self) -> str:
        """텔레그램 일일 브리핑 메시지용 리포트 포맷팅"""
        today_data = self.get_daily_summary()
        month_data = self.get_monthly_summary()
        
        google_used = today_data.get("google_cse_calls", 0)
        google_rem = max(0, 100 - google_used)
        today_krw = today_data.get("estimated_cost_krw", 0.0)
        month_krw = month_data.get("estimated_cost_krw", 0.0)
        
        report = (
            f"<b>💰 [API 비용 및 쿼리 현황]</b>\n"
            f"• <b>오늘 비용</b>: 약 {today_krw:,.1f}원\n"
            f"  - Google CSE: {google_used}/100회 (잔여: {google_rem}회)\n"
            f"  - Unsplash/Pexels: {today_data.get('unsplash_calls', 0) + today_data.get('pexels_calls', 0)}회 (무료)\n"
            f"  - Gemini 심사: {today_data.get('gemini_multimodal_calls', 0)}회 ({today_data.get('gemini_input_tokens', 0) + today_data.get('gemini_output_tokens', 0):,} 토큰)\n"
            f"• <b>이번 달 누적</b>: 약 {month_krw:,.1f}원 (안전 가동 중)"
        )
        return report

    def _empty_daily_record(self) -> dict:
        return {
            "google_cse_calls": 0,
            "unsplash_calls": 0,
            "pexels_calls": 0,
            "gemini_multimodal_calls": 0,
            "gemini_input_tokens": 0,
            "gemini_output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimated_cost_krw": 0.0
        }

    def _empty_monthly_record(self) -> dict:
        return {
            "google_cse_calls": 0,
            "unsplash_calls": 0,
            "pexels_calls": 0,
            "gemini_multimodal_calls": 0,
            "gemini_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimated_cost_krw": 0.0
        }

class _FileLock:
    def __init__(self, lock_file_path: str):
        self.lock_file_path = lock_file_path
        self.f = None
        
    def __enter__(self):
        self.f = open(self.lock_file_path, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.f:
                fcntl.flock(self.f, fcntl.LOCK_UN)
                self.f.close()
        except Exception:
            pass
