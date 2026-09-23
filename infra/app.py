#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.pantry_mcp_stack import PantryMcpStack

app = cdk.App()
PantryMcpStack(app, "PantryMcpStack")
app.synth()
