"""Prospective sensor route through the unchanged single-use CPU evaluator.

The process has exactly one endpoint; no existing population source is edited.
Both this route and its imported execution implementation are frozen in each
campaign before any research request. This is an adapter, not research policy.
"""

from scitaste.benchmark import sensor_drift_task_data
from scripts import serve_population_confirmation

serve_population_confirmation.endpoint = sensor_drift_task_data


if __name__ == "__main__":
    serve_population_confirmation.main()
