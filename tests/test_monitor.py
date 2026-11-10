"""수집기 규칙 시험 — 인터넷 없이 날짜 읽기·맞춤 점수·캘린더·주간 요약만.

  python -m unittest discover -s tests
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import monitor as M                                                       # noqa: E402

M.TODAY = dt.date(2026, 11, 10)        # 모든 시험의 '오늘' (화요일)

CFG = {
    "interests": {"star": 4, "min_push": 0, "groups": [
        {"name": "학생 대상", "weight": 4, "words": ["의대생", "학생연구", "서포터즈", "student"]},
        {"name": "연구 방법", "weight": 4, "words": ["메타분석", "문헌고찰"]},
        {"name": "의료 AI", "weight": 2, "words": ["인공지능", "AI", "LLM"]},
        {"name": "심장·심전도", "weight": 3, "words": ["심전도", "ECG"]},
        {"name": "대상 아님", "weight": -6, "words": ["희망기업", "박사과정", "환불"]},
    ]},
    "categories": {"research": {"name": "연구·인턴", "push": True}, "data": {"name": "데이터", "push": False}},
    "notify": {"max_per_run": 10, "digest": {"enabled": True, "weekday": 0, "hour": 7}},
    "app": {"url": "https://example.test/app/"},
}


def item(title, **kw):
    return {"id": kw.pop("id", title), "title": title, "link": "https://example.test/x", "source": "시험 출처",
            "category": "research", "date": "", "deadline": "", "extra": "", "first_seen": "2026-11-09T18:26:33",
            "baseline": False} | kw


class Deadline(unittest.TestCase):
    def test_title_formats(self):
        cases = {
            "공모전 안내(공모기간:~11/29까지)": "2026-11-29",
            "양성 사업 공고('26.11.18.(수), 15시 제출 마감)": "2026-11-18",
            "제출기한: ~11/22(일)": "2026-11-22",
            "참가자 모집 11월 30일까지": "2026-11-30",
            "D-4": "2026-11-14",
            "Nov 02 - Dec 15, 2026": "2026-12-15",
            "2026-12-01T23:59:00Z": "2026-12-01",
            "접수 2026-11-01 ~ 2026-11-20": "2026-11-20",      # 줄표로 쓴 기간(전에는 못 읽었다)
            "모집 2026.11.01 ~ 2026.11.25": "2026-11-25",
            "겨울 인턴 모집 (~1/10)": "2027-01-10",             # 연말에 올라온 새해 마감
        }
        for text, want in cases.items():
            self.assertEqual(M.parse_deadline(text), want, text)

    def test_not_a_deadline(self):
        for text in ("COVID-19 대응 보고서", "2026년 교육일정 안내", "", "MONAI 1.6.1"):
            self.assertEqual(M.parse_deadline(text), "", text)

    def test_norm_date(self):
        self.assertEqual(M.norm_date("2026.11.9"), "2026-11-09")
        self.assertEqual(M.norm_date("등록일 2026-11-04 조회 12"), "2026-11-04")
        self.assertEqual(M.norm_date("없음"), "")


class PageDeadline(unittest.TestCase):
    def test_reads_end_of_labelled_period(self):
        cases = {
            "모집 대상 의대생 접수기간 : 2026. 11. 3.(월) ~ 11. 21.(금) 18:00 선발 결과 발표 12. 1.": "2026-11-21",
            "신청 기간: 2026년 11월 5일 ~ 2026년 11월 28일 교육 일시 12월 6일(토)": "2026-11-28",
            "● 신청마감 : 11.20(금) 까지 ● 장소 : 서울": "2026-11-20",
            "Application deadline: 2026-12-15 Program dates: 2027-01-05": "2026-12-15",
            "지원 기간 2026.12.20 ~ 2027.1.8": "2027-01-08",
        }
        for text, want in cases.items():
            self.assertEqual(M.page_deadline(text), want, text)

    def test_no_label_no_guess(self):
        # 날짜가 있어도 '접수·신청·모집 기간/마감' 꼬리표가 없으면 읽지 않는다
        self.assertEqual(M.page_deadline("행사 일시 2026.11.20(금) 14:00 장소 대강당"), "")
        self.assertEqual(M.page_deadline("교육 기간 2026.12.1 ~ 12.5 문의 02-000-0000"), "")
        self.assertEqual(M.page_deadline(""), "")

    def test_next_field_date_is_not_taken(self):
        # 접수기간 뒤에 날짜가 없고 바로 '발표' 날짜가 오면 그 날짜를 마감으로 삼지 않는다
        self.assertEqual(M.page_deadline("접수 기간: 상시 접수 선발 결과 발표 2026.12.1"), "")

    def test_rejects_dates_before_posting_or_far_away(self):
        self.assertEqual(M.page_deadline("접수기간: 2026.10.1 ~ 2026.10.20", posted="2026-11-05"), "")
        self.assertEqual(M.page_deadline("접수기간: 2024.3.1 ~ 2024.3.20"), "")


class Score(unittest.TestCase):
    def test_groups_count_once_and_add_up(self):
        sc, tags = M.score_item(item("한국코크란 서포터즈 1기 모집 — 의대생 메타분석 문헌고찰"), CFG)
        self.assertEqual((sc, tags), (8, ["학생 대상", "연구 방법"]))

    def test_ascii_words_match_on_word_boundary(self):
        self.assertEqual(M.score_item(item("Training available for trainees"), CFG)[0], 0)       # 'ai' 는 낱말이 아니다
        self.assertEqual(M.score_item(item("AI for Medicine: A Global Student Hackathon"), CFG)[0], 6)
        self.assertEqual(M.score_item(item("12-lead ECG dataset v1.0"), CFG)[1], ["심장·심전도"])
        self.assertEqual(M.score_item(item("의료AI 경진대회"), CFG)[0], 2)                         # 한글 옆에 붙은 AI

    def test_negative_group_outweighs_interest(self):
        sc, tags = M.score_item(item("헬스케어 인공지능 투자포럼 희망기업 모집"), CFG)
        self.assertLess(sc, 0)
        self.assertIn("대상 아님", tags)

    def test_extra_text_is_scored_too(self):
        self.assertEqual(M.score_item(item("Spring challenge", extra="open to undergraduate student teams"), CFG)[0], 4)


class Push(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._phone = M.phone
        M.phone = lambda cfg, title, body, click=None, tags=None, app_url=None, priority=4: \
            self.sent.append({"title": title, "body": body, "priority": priority})

    def tearDown(self):
        M.phone = self._phone

    def test_off_target_is_not_pushed_and_star_goes_first(self):
        new = [item("일반 공지"), item("박사과정 연구계획서 심사"), item("학생연구 1기 모집", deadline="2026-11-20"),
               item("새 데이터", category="data")]
        M.notify_new(CFG, new)
        self.assertEqual([s["title"] for s in self.sent], ["★ [연구·인턴] 시험 출처", "[연구·인턴] 시험 출처"])
        self.assertEqual([s["priority"] for s in self.sent], [4, 3])
        self.assertIn("마감 2026-11-20", self.sent[0]["body"])
        self.assertIn("맞춤: 학생 대상", self.sent[0]["body"])

    def test_page_deadline_is_labelled_as_guess(self):
        M.notify_new(CFG, [item("의대생 인턴 모집", deadline="2026-11-20", deadline_src="page")])
        self.assertIn("추정", self.sent[0]["body"])

    def test_weekly_digest_once_on_monday_morning(self):
        st = {"items": {"a": item("이번 주 마감 공고", deadline="2026-11-18"),
                        "b": item("다음 달 공고", deadline="2026-12-20"),
                        "c": item("희망기업 모집", deadline="2026-11-17")}}
        monday = dt.datetime(2026, 11, 16, 9, 17)
        self.assertFalse(M.weekly_digest(CFG, st, dt.datetime(2026, 11, 10, 9, 17)))      # 화요일
        self.assertFalse(M.weekly_digest(CFG, st, dt.datetime(2026, 11, 16, 3, 17)))      # 월요일 새벽
        self.assertTrue(M.weekly_digest(CFG, st, monday))
        self.assertEqual(self.sent[-1]["title"], "이번 주 마감 1건")                       # 다음 달 · 대상 아님은 빠진다
        self.assertFalse(M.weekly_digest(CFG, st, monday.replace(hour=12)))               # 같은 주에 두 번 보내지 않는다
        self.assertEqual(len(self.sent), 1)


class Calendar(unittest.TestCase):
    def test_ics_events_and_folding(self):
        long_title = "의과대학 학생 연구 프로그램 2027년도 상반기 참가자 모집 공고 — " + "아주 긴 제목 " * 6
        ics = M.build_ics([item(long_title, id="k1", deadline="2026-11-20", deadline_src="page"),
                           item("쉼표, 세미콜론; 줄\n바꿈", id="k2", deadline="2026-11-15")])
        lines = ics.split("\r\n")
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertEqual(lines[-2], "END:VCALENDAR")
        self.assertTrue(all(len(x.encode("utf-8")) <= 75 for x in lines))                 # RFC 5545 줄 길이
        self.assertLess(ics.index("20261115"), ics.index("20261120"))                     # 마감 빠른 순
        self.assertIn("DTSTART;VALUE=DATE:20261120", ics)
        self.assertIn("DTEND;VALUE=DATE:20261121", ics)
        self.assertIn("마감 (추정) · ", ics.replace("\r\n ", ""))
        self.assertIn(r"쉼표\, 세미콜론\; 줄\n바꿈", ics.replace("\r\n ", ""))
        self.assertEqual(ics.count("BEGIN:VEVENT"), 2)
        self.assertEqual(len({x for x in lines if x.startswith("UID:")}), 2)

    def test_app_items_carry_score_and_tags(self):
        st = {"items": {"시험 출처::1": item("학생연구 1기 모집", deadline="2026-11-20"),
                        "시험 출처::2": item("옛 글", first_seen="2026-01-01T00:00:00")}}
        out = M.app_items(st, CFG)
        self.assertEqual([(x["id"], x["score"], x["tags"]) for x in out], [("시험 출처::1", 4, ["학생 대상"])])


class Filter(unittest.TestCase):
    def test_similar_headlines(self):
        self.assertTrue(M.similar("의사과학자 양성기관 추가 모집 1인당 5000만원", "의사과학자 양성기관 추가 모집…연 최대 5000만원 지원"))
        self.assertFalse(M.similar("의료 AI 해커톤 참가자 모집", "보건의료 데이터 공개 확대"))

    def test_matches_require_and_exclude(self):
        cfg = {"keywords": {"include": ["연구"], "exclude": ["학자금대출"]}}
        src = {"filter": True, "require": ["모집"]}
        self.assertTrue(M.matches(item("학생 연구 인턴 모집"), src, cfg))
        self.assertFalse(M.matches(item("학생 연구 성과 발표"), src, cfg))
        self.assertFalse(M.matches(item("연구 장학 모집 — 학자금대출 안내"), src, cfg))


if __name__ == "__main__":
    unittest.main()
