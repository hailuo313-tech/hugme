import asyncio

from services.call_broadcast.ffmpeg_pipeline import normalize_video_for_telegram_call


async def main() -> None:
    result = await normalize_video_for_telegram_call(
        "/tmp/noaudio.mp4",
        trace_id="test",
        in_place=False,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
