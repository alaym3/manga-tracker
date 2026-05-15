SELECT last_pulled_at
FROM mage.pipeline_checkpoints
WHERE pipeline_name = '{pipeline_name}';