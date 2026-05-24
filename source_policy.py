from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceRule:
    domain: str
    tier: str
    outlet_name: str
    group: str


class SourcePolicy:
    TIER1 = [
        SourceRule("pbc.gov.cn", "tier1", "中国人民银行", "official"),
        SourceRule("mof.gov.cn", "tier1", "财政部", "official"),
        SourceRule("ndrc.gov.cn", "tier1", "国家发改委", "official"),
        SourceRule("stats.gov.cn", "tier1", "国家统计局", "official"),
        SourceRule("csrc.gov.cn", "tier1", "证监会", "official"),
        SourceRule("nfra.gov.cn", "tier1", "国家金融监督管理总局", "official"),
        SourceRule("safe.gov.cn", "tier1", "国家外汇管理局", "official"),
        SourceRule("www.gov.cn", "tier1", "中国政府网", "official"),
        SourceRule("gov.cn", "tier1", "中国政府网", "official"),
    ]

    TIER2 = [
        SourceRule("caixin.com", "tier2", "财新", "media_depth"),
        SourceRule("yicai.com", "tier2", "第一财经", "media_depth"),
        SourceRule("21jingji.com", "tier2", "21世纪经济报道", "media_depth"),
        SourceRule("cls.cn", "tier2", "财联社", "media_fast"),
        SourceRule("stcn.com", "tier2", "证券时报", "media_market"),
        SourceRule("cs.com.cn", "tier2", "中国证券报", "media_market"),
        SourceRule("cnstock.com", "tier2", "上海证券报", "media_market"),
        SourceRule("financialnews.com.cn", "tier2", "金融时报", "media_official"),
        SourceRule("ce.cn", "tier2", "中国经济网", "media_official"),
        SourceRule("jiemian.com", "tier2", "界面新闻", "media_general"),
        SourceRule("thepaper.cn", "tier2", "澎湃新闻", "media_general"),
        SourceRule("eeo.com.cn", "tier2", "经济观察报", "media_depth"),
        SourceRule("nbd.com.cn", "tier2", "每日经济新闻", "media_general"),
    ]

    def __init__(self):
        self.rules = self.TIER1 + self.TIER2

    def resolve(self, url: str) -> SourceRule | None:
        domain = self.extract_domain(url)
        for rule in self.rules:
            if domain == rule.domain or domain.endswith("." + rule.domain) or rule.domain in domain:
                return rule
        return None

    def domains_by_group(self, groups: List[str] | None = None) -> List[str]:
        if not groups:
            return [rule.domain for rule in self.rules]
        return [rule.domain for rule in self.rules if rule.group in groups]

    @staticmethod
    def extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            return "unknown"
