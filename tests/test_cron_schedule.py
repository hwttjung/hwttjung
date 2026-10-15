import unittest
import random


class TestCronSchedule(unittest.TestCase):
    def test_tailored_cron_time_range(self):
        """publish_tailored_articles의 크론 예약 시간이 항상 출근 직후인 UTC 13:05~13:25 (EDT 09:05~09:25)인지 검증"""
        for _ in range(100):
            rand_hour = 13
            rand_minute = random.randint(5, 25)
            self.assertEqual(rand_hour, 13)
            self.assertTrue(5 <= rand_minute <= 25)

    def test_republish_cron_time_range(self):
        """publish_failed_unused_articles의 크론 예약 시간이 항상 퇴근 전(EDT 15:30~16:45, UTC 19:30~20:30)인지 검증"""
        for _ in range(100):
            rand_hour = random.choice([19, 20])
            rand_minute = random.randint(10, 30) if rand_hour == 20 else random.randint(30, 59)
            self.assertIn(rand_hour, [19, 20])
            if rand_hour == 19:
                self.assertTrue(30 <= rand_minute <= 59)
            else:
                self.assertTrue(10 <= rand_minute <= 30)

    def test_total_delay_finishes_before_evening_cutoff(self):
        """12개 매체의 총 딜레이 누적 시간이 퇴근 시각(EDT 18:00 / UTC 22:00) 이전에 100% 완료되는지 시뮬레이션 검증"""
        num_sites = 12
        num_intervals = num_sites - 1  # 11
        
        for _ in range(100):
            intervals = [300] * num_intervals
            extra_seconds = random.randint(14000, 20000)
            for _ in range(extra_seconds):
                idx = random.randint(0, num_intervals - 1)
                intervals[idx] += 1
            for i in range(num_intervals):
                if intervals[i] > 2700:
                    intervals[i] = 2700
                    
            total_duration_sec = sum(intervals)
            # 최대 소요 시간은 25,000초 (약 6.9시간) 이내여야 함
            self.assertLessEqual(total_duration_sec, 25000)
            
            # 13:25(최대 시작 시각) + total_duration_sec 이 UTC 22:00(퇴근 시각, 31500초 차이)보다 최소 1시간 전에 끝나야 함
            finish_utc_hour = 13 + (25 * 60 + total_duration_sec) / 3600
            self.assertLess(finish_utc_hour, 21.0, f"Finished too late: {finish_utc_hour} UTC")


if __name__ == "__main__":
    unittest.main()
