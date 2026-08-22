# AWS CodeBuild CI: test, build, and push both application images

The repository-root `buildspec.yml` runs the Python tests first. If `pytest`
returns a non-zero exit code, CodeBuild stops before `docker build` and no image
is pushed. A successful build pushes backend and frontend images with both an
immutable commit tag and `latest`.

## Required resources

Use the same AWS Region for CodeBuild and ECR. These instructions use
`eu-west-2`; substitute your deployment Region if different.

1. In **Amazon ECR > Private repositories**, create two repositories, such as
   `cardio-clinical-agent-backend-geetha` and
   `cardio-clinical-agent-frontend-geetha`. Enable tag immutability if the later
   deployment will use only commit tags; the current buildspec also updates
   `latest`, so leave immutability disabled while using both tags.
2. In **AWS CodeBuild > Build projects**, create a project and choose **GitHub**
   as the source. Connect the repository and select the branch to build.
3. Choose a managed Linux image, **Standard** image, and enable **Privileged**
   mode. Docker image builds require privileged mode in this configuration.
4. Choose **Use a buildspec file** and leave the name as `buildspec.yml`.
5. Add these environment variables as plain text (they are identifiers, not
   secrets):

   - `AWS_ACCOUNT_ID`: the 12-digit account that owns the ECR repository
   - `AWS_DEFAULT_REGION`: for example `eu-west-2`
   - `BACKEND_REPO_NAME`: for example `cardio-clinical-agent-backend-geetha`
   - `FRONTEND_REPO_NAME`: for example `cardio-clinical-agent-frontend-geetha`

Do not add application secrets, DynamoDB settings, or medication API keys to
this CI project. They belong in the later runtime/deployment configuration.

## CodeBuild service-role permissions

Add the following least-privilege statement to the CodeBuild project's service
role. Replace the account, Region, and repository name in `Resource`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PushBackendImage",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart"
      ],
      "Resource": [
        "arn:aws:ecr:eu-west-2:123456789012:repository/cardio-clinical-agent-backend-geetha",
        "arn:aws:ecr:eu-west-2:123456789012:repository/cardio-clinical-agent-frontend-geetha"
      ]
    }
  ]
}
```

## Trigger on a GitHub push

In the CodeBuild project, open **Build details > Primary source webhook**, choose
**Rebuild every time a code change is pushed**, and add a `PUSH` event filter.
Add a branch-name filter such as `^refs/heads/main$` if only `main` should publish
an image. Save, then use **Start build** once to validate the project before
pushing a small commit to test the webhook.

In the build log, the expected order is `pytest`, ECR login, `docker build`, and
the two `docker push` commands. The output artifact `image-detail.json` records
the immutable image URI for the later deployment stage.

## Runtime settings that are separate from CI

The running backend (for example an ECS task) must receive:

```text
PATIENT_DATA_MODE=dynamodb
DYNAMODB_TABLE_NAME=<exact table name>
AWS_REGION=<the table's Region>
```

Its task role, not the CodeBuild role, needs `dynamodb:Query` on the table. The
medication lookup additionally requires `MEDICATION_API_ENABLED=true` and
outbound HTTPS access. These settings affect the deployed app; placing them only
in CodeBuild will not fix runtime retrieval.
