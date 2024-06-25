import logging
import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, Response

from opentelemetry.propagate import inject
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette_prometheus import PrometheusMiddleware, metrics

from otlp import setting_otlp, get_tracer


#############################
#          Logging          #
#############################


class EndpointFilter(logging.Filter):
    # Uvicorn endpoint access log filter
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("GET /metrics") == -1

# Filter out /endpoint
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


#################################
#          ENVIRONMENT          #
#################################


OTLP_ENDPOINT = os.environ["OTLP_ENDPOINT"]
EXPOSE_PORT = os.environ["EXPOSE_PORT"]


#################################
#          APP-Setting          #
#################################


app = FastAPI()

# Setting metrics middleware
app.add_middleware(PrometheusMiddleware, filter_unhandled_paths=True)
app.add_route("/metrics", metrics)

# Setting OpenTelemetry exporter
setting_otlp(app, endpoint=OTLP_ENDPOINT, service_name="FastAPI", compose_service="fastapi")
tracer = get_tracer()


#################################
#          MAIN-ROUTES          #
#################################


@app.get("/")
async def root():
    logging.error("Hello World")
    return {"Hello": "World"}


@app.get("/multi_span")
async def multi_span():
    with tracer.start_as_current_span("first-span") as span:
        time.sleep(1)
        logging.info("first span!")
    with tracer.start_as_current_span("second-span"):
        time.sleep(1)
        logging.info("second span!")
    return {"Hello": "World"}


@app.get("/nested_span")
async def nested_span():
    prop = TraceContextTextMapPropagator()
    carrier = {}

    with tracer.start_as_current_span("outer-span") as span:
        prop.inject(carrier=carrier)
        logging.info("Carrier after injecting span context", carrier)

    context = prop.extract(carrier=carrier)
    with tracer.start_as_current_span("inner-span", context=context):
        logging.info("Hello World")

    return {"Hello": "World"}


@app.get("/chain")
async def chain(response: Response):
    headers = {}
    inject(headers)  # inject trace info to header
    logging.critical(headers)

    async with httpx.AsyncClient() as client:
        await client.get(
            f"http://localhost:{EXPOSE_PORT}/",
            headers=headers,
        )
    async with httpx.AsyncClient() as client:
        await client.get(
            f"http://localhost:{EXPOSE_PORT}/io_task",
            headers=headers,
        )
    async with httpx.AsyncClient() as client:
        await client.get(
            f"http://localhost:{EXPOSE_PORT}/cpu_task",
            headers=headers,
        )
    logging.info("Chain Finished")
    return {"path": "/chain"}


@app.get("/triton")
def triton():
    headers = {}
    inject(headers)  # inject trace info to header
    logging.critical(headers)

    import numpy as np
    from tritonclient.http import InferenceServerClient, InferInput, InferRequestedOutput

    triton_client = InferenceServerClient("triton:8000")

    inputs = []
    outputs = []
    inputs.append(InferInput("INPUT0", [1, 16], "INT32"))
    inputs.append(InferInput("INPUT1", [1, 16], "INT32"))

    # Initialize the data
    inputs[0].set_data_from_numpy(np.arange(16).reshape(1, 16).astype("int32"), binary_data=False)
    inputs[1].set_data_from_numpy(np.arange(16).reshape(1, 16).astype("int32"), binary_data=True)

    outputs.append(InferRequestedOutput("OUTPUT0", binary_data=True))
    outputs.append(InferRequestedOutput("OUTPUT1", binary_data=False))
    query_params = {"test_1": 1, "test_2": 2}
    results = triton_client.infer(
        "simple",
        inputs,
        outputs=outputs,
        query_params=query_params,
        headers=headers,
        request_compression_algorithm="gzip",
        response_compression_algorithm="gzip",
    )

    logging.info(results.get_response())
    logging.info(f"{results.as_numpy('OUTPUT0')}")
    logging.info(f"{results.as_numpy('OUTPUT1')}")

    return {}



################################
#          SUB-ROUTES          #
################################


@app.get("/io_task")
async def io_task():
    time.sleep(1)
    logging.error("io task")
    return "IO bound task finish!"


@app.get("/cpu_task")
async def cpu_task():
    for i in range(1000):
        _ = i * i * i
    logging.error("cpu task")
    return "CPU bound task finish!"


# @app.get("/random_status")
# async def random_status(response: Response):
#     response.status_code = random.choice([200, 200, 300, 400, 500])
#     logging.error("random status")
#     return {"path": "/random_status"}


# @app.get("/random_sleep")
# async def random_sleep(response: Response):
#     time.sleep(random.randint(0, 5))
#     logging.error("random sleep")
#     return {"path": "/random_sleep"}


# @app.get("/error_test")
# async def error_test(response: Response):
#     logging.error("got error!!!!")
#     raise ValueError("value error")


if __name__ == "__main__":
    # update uvicorn access logger format
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = \
        "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] - %(message)s"
    uvicorn.run(app, host="0.0.0.0", port=int(EXPOSE_PORT), log_config=log_config)
