#!/usr/bin/env python3
"""Self-test for the price table parser. Runs before every scheduled update."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import datetime as dt  # noqa: E402

from update_prices import parse_comex_chart, parse_metal_table, parse_number  # noqa: E402

SAMPLE = """
<html><body><table>
<tr><th>date</th><th>LME Copper Cash-Settlement</th><th>LME Copper 3-month</th><th>LME Copper stock</th></tr>
<tr><td>18. November 2026</td><td>12,750.00</td><td>12,773.50</td><td>327,400</td></tr>
<tr><td> 17. November 2026 </td><td><b>13,225.50</b></td><td>13,211.00</td><td>327,600</td></tr>
<tr><td>25. December 2026</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>02. Januar 2026</td><td>12,571.00</td><td>-</td><td>1</td></tr>
<tr><th>date</th><th>LME Copper Cash-Settlement</th><th>LME Copper 3-month</th><th>LME Copper stock</th></tr>
<tr><td>31. February 2026</td><td>12,000.00</td><td>12,000.00</td><td>1</td></tr>
<tr><td>01. October 2026</td><td>999,999.00</td><td>1.00</td><td>1</td></tr>
<tr><td>not a date</td><td>12,000.00</td></tr>
</table></body></html>
"""


def main() -> int:
    rows = parse_metal_table(SAMPLE, (2000.0, 60000.0))
    expected = {
        "2026-11-18": (12750.0, 12773.5),
        "2026-11-17": (13225.5, 13211.0),
        "2026-01-02": (12571.0, None),
    }
    assert rows == expected, f"parser returned {rows}"
    assert parse_number("3,095.00") == 3095.0
    assert parse_number("-") is None
    assert parse_number("12.750,00") is None  # German number format must not be misread
    assert parse_metal_table("<html><p>layout changed</p></html>", (1, 2)) == {}
    # COMEX chart: four daily bars at midnight New York time; one gap, and the last one is today's open session.
    chart = (
        '{"chart":{"result":[{"meta":{"gmtoffset":-18000},'
        '"timestamp":[1795064400,1795150800,1795237200,1795323600],'
        '"indicators":{"quote":[{"close":[5.625,null,5.5465,5.60]}]}}],"error":null}}'
    )
    bars = parse_comex_chart(chart, (0.5, 30.0), dt.date(2026, 11, 22))
    assert bars == {"2026-11-19": 5.625, "2026-11-21": 5.5465}, f"comex parser returned {bars}"
    print("parser self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
