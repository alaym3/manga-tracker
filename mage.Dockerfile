ARG MAGEAI_VERSION=0.9.76
FROM mageai/mageai:${MAGEAI_VERSION}

ARG PROJECT_NAME=manga_tracker
ARG USER_CODE_PATH=/home/src/${PROJECT_NAME}

# Note: this overwrites the requirements.txt file in your new project on first run.
# You can delete this line for the second run :)

COPY requirements.txt ${USER_CODE_PATH}/requirements.txt
RUN pip install -r ${USER_CODE_PATH}/requirements.txt

# init dbt project if it doesn't already exist (e.g. on first run)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]