from aws_cdk import CfnOutput, CfnParameter, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_lambda as _lambda
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct


class PantryMcpStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        keycloak_url = CfnParameter(self, "KeycloakUrl", type="String")
        keycloak_realm = CfnParameter(self, "KeycloakRealm", type="String")
        keycloak_client_id = CfnParameter(self, "KeycloakClientId", type="String")
        keycloak_username = CfnParameter(self, "KeycloakUsername", type="String")
        keycloak_password = CfnParameter(self, "KeycloakPassword", type="String", no_echo=True)
        restrackit_base_url = CfnParameter(self, "RestrackitBaseUrl", type="String")
        restrackit_store_id = CfnParameter(self, "RestrackitStoreId", type="String")
        mcp_auth_token = CfnParameter(self, "McpAuthToken", type="String", no_echo=True)

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
                "KEYCLOAK_CLIENT_ID": keycloak_client_id.value_as_string,
                "KEYCLOAK_USERNAME": keycloak_username.value_as_string,
                "KEYCLOAK_PASSWORD": keycloak_password.value_as_string,
                "RESTRACKIT_BASE_URL": restrackit_base_url.value_as_string,
                "RESTRACKIT_STORE_ID": restrackit_store_id.value_as_string,
                "MCP_AUTH_TOKEN": mcp_auth_token.value_as_string,
            },
        )

        http_api = apigwv2.HttpApi(
            self,
            "PantryMcpApi",
            default_integration=apigwv2_integrations.HttpLambdaIntegration(
                "PantryMcpIntegration", fn
            ),
        )

        CfnOutput(self, "ApiUrl", description="Public URL of the MCP server", value=http_api.api_endpoint)
