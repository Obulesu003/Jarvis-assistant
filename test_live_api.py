# Test with full config matching main.py
import logging  # migrated from print()
import asyncio
import traceback

try:
    import google.genai as genai
    from google.genai import types

    client = genai.Client(
        api_key="REDACTED_LEAKED_KEY",
        http_options={"api_version": "v1beta"}
    )

    # Minimal tools for testing
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    }]

    async def test():
        try:
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                output_audio_transcription={},
                input_audio_transcription={},
                system_instruction="You are JARVIS. Keep responses brief.",
                tools=[{"function_declarations": tools}],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Charon"
                        )
                    )
                ),
            )
            async with client.aio.live.connect(
                model="models/gemini-2.5-flash-native-audio-preview-12-2025",
                config=config
            ) as session:
                logging.getLogger(__name__).info('LIVE_API: OK - Connected with full config!')
                await session.send_client_content(
                    turns={"parts": [{"text": "Hello"}]},
                )
                logging.getLogger(__name__).info('LIVE_API: Sent message...')
                async for response in session.receive():
                    if response.text:
                        logging.getLogger(__name__).info('LIVE_API: Text: {response.text[:200]}')
                    if hasattr(response, 'audio') and response.audio:
                        logging.getLogger(__name__).info('LIVE_API: Received audio response')
                    if response.server_content:
                        logging.getLogger(__name__).info('LIVE_API: Server content: {response.server_content}')
                await session.send_end()
        except Exception as e:
            logging.getLogger(__name__).info('LIVE_API: FAILED - {type(e).__name__}: {e}')
            traceback.print_exc()

    asyncio.run(test())
except Exception as e:
    logging.getLogger(__name__).info('Setup error: {e}')
    traceback.print_exc()
