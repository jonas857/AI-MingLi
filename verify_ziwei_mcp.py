import asyncio
import json
import os
import uuid
from ziwei_client import ZiweiClient


async def main():
    request_id = str(uuid.uuid4())
    client = ZiweiClient(request_id=request_id)

    tools = await client.list_tools()
    os.makedirs(os.path.join("local_data", "logs"), exist_ok=True)

    chart = await client.generate_chart(
        name="测试用户",
        birth_date="1990-05-15",
        birth_time="14:30",
        gender="male",
        location={"province": "上海", "city": "上海", "longitude": 121.4737, "latitude": 31.2304},
    )

    chart_id = (
        (chart.get("chartId") if isinstance(chart, dict) else None)
        or (chart.get("chart_id") if isinstance(chart, dict) else None)
        or (chart.get("id") if isinstance(chart, dict) else None)
        or (((chart.get("data") or {}).get("chartId")) if isinstance(chart, dict) else None)
        or (((chart.get("data") or {}).get("id")) if isinstance(chart, dict) else None)
    )

    out = {"request_id": request_id, "tools": tools, "chart_id": chart_id, "chart": chart, "interpret": None}

    if chart_id:
        interpret = await client.interpret_chart(
            chart_id=str(chart_id),
            aspects=["personality", "career", "wealth"],
            detail_level="basic",
        )
        out["interpret"] = interpret

    with open(os.path.join("local_data", "logs", "ziwei_verify_output.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())
