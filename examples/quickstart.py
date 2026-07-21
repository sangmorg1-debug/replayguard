from replayguard import Recorder, current_recorder, model_call, tool_call


@tool_call("weather.lookup")
def weather(city: str) -> dict:
    return {"city": city, "temperature_c": 18}


@model_call("demo.answer")
def answer(question: str) -> str:
    result = weather("Seattle")
    return f"{question}: {result['temperature_c']}C"


if current_recorder() is None:
    with Recorder("quickstart", capture_content=True):
        print(answer("Current weather"))
else:
    print(answer("Current weather"))
