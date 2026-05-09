#!/bin/bash
set -e

DBT_PROJECT_DIR="/home/src/${PROJECT_NAME}/dbt/${DBT_PROJECT_NAME}"

# Only init if the dbt project doesn't already exist
if [ ! -f "$DBT_PROJECT_DIR/dbt_project.yml" ]; then
    echo "dbt project not found — running dbt init..."
    mkdir -p "/home/src/${PROJECT_NAME}/dbt"
    cd "/home/src/${PROJECT_NAME}/dbt"
    dbt init ${DBT_PROJECT_NAME} --skip-profile-setup
    echo "dbt init complete."
else
    echo "dbt project already exists — skipping init."
fi

# Hand off to the normal Mage startup
cd "/home/src"
exec mage start ${PROJECT_NAME}