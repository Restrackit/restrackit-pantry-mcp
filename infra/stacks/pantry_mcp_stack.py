from aws_cdk import CfnOutput, CfnParameter, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct

# ponytail: this aws-cdk-lib version has no direct Lambda-env-from-Secrets-Manager
# binding (no `_lambda.Secret`), so only the secret NAME is injected as a plain env
# var; `pantry_mcp/config.py` fetches the value once at startup via boto3. Upgrade to
# passing the value directly if a future aws-cdk-lib adds that construct.
TOKEN_EXCHANGE_SECRET_NAME = "pantry-mcp/token-exchange-client"


class PantryMcpStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        keycloak_url = CfnParameter(self, "KeycloakUrl", type="String")
        keycloak_realm = CfnParameter(self, "KeycloakRealm", type="String")
        keycloak_connector_client_id = CfnParameter(self, "KeycloakConnectorClientId", type="String")
        keycloak_exchange_client_id = CfnParameter(self, "KeycloakExchangeClientId", type="String")
        restrackit_backend_client_id = CfnParameter(self, "RestrackitBackendClientId", type="String")
        restrackit_base_url = CfnParameter(self, "RestrackitBaseUrl", type="String")

        fn = PythonFunction(
            self,
            "PantryMcpFunction",
            entry="..",
            index="pantry_mcp/lambda_handler.py",
            handler="handler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            timeout=Duration.seconds(15),
            memory_size=256,
            bundling=BundlingOptions(
                asset_excludes=[
                    ".venv",
                    ".git",
                    ".pytest_cache",
                    ".ruff_cache",
                    "*.egg-info",
                    "infra",
                    "tests",
                ],
            ),
            environment={
                "KEYCLOAK_URL": keycloak_url.value_as_string,
                "KEYCLOAK_REALM": keycloak_realm.value_as_string,
                "KEYCLOAK_CONNECTOR_CLIENT_ID": keycloak_connector_client_id.value_as_string,
                "KEYCLOAK_EXCHANGE_CLIENT_ID": keycloak_exchange_client_id.value_as_string,
                "KEYCLOAK_EXCHANGE_CLIENT_SECRET_NAME": TOKEN_EXCHANGE_SECRET_NAME,
                "RESTRACKIT_BACKEND_CLIENT_ID": restrackit_backend_client_id.value_as_string,
                "RESTRACKIT_BASE_URL": restrackit_base_url.value_as_string,
            },
        )

        # Un solo secret, non per-tenant: le credenziali dell'exchanger sono
        # uguali per tutti i tenant (Task 4, TokenExchanger).
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:{TOKEN_EXCHANGE_SECRET_NAME}-*"
                ],
            )
        )

        http_api = apigwv2.HttpApi(
            self,
            "PantryMcpApi",
            create_default_stage=False,
            default_integration=apigwv2_integrations.HttpLambdaIntegration(
                "PantryMcpIntegration", fn
            ),
        )
        apigwv2.HttpStage(
            self,
            "PantryMcpStage",
            http_api=http_api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigwv2.ThrottleSettings(rate_limit=20, burst_limit=40),
        )

        CfnOutput(self, "ApiUrl", description="Public URL of the MCP server", value=http_api.api_endpoint)
