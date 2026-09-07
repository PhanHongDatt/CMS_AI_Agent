"""AWS read-only MCP tools."""

from datetime import datetime, timezone
from typing import Any

from mcp.base import MCPConnectionError, ToolKind, ToolResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AWSReadonlyTools:
    """Wraps boto3 clients for read-only AWS operations.

    Inject boto3 clients for testability. Uses least-privilege IAM role.
    """

    def __init__(self, ec2_client: Any, elbv2_client: Any, s3_client: Any) -> None:
        self._ec2 = ec2_client
        self._elbv2 = elbv2_client
        self._s3 = s3_client

    async def aws_get_ec2_health(self, instance_ids: list[str] | None = None) -> ToolResult:
        try:
            kwargs: dict[str, Any] = {}
            if instance_ids:
                kwargs["InstanceIds"] = instance_ids
            status = self._ec2.describe_instance_status(**kwargs)
            items = [
                {
                    "instance_id": s["InstanceId"],
                    "state": s.get("InstanceState", {}).get("Name"),
                    "system_status": s.get("SystemStatus", {}).get("Status"),
                    "instance_status": s.get("InstanceStatus", {}).get("Status"),
                }
                for s in status.get("InstanceStatuses", [])
            ]
            return ToolResult(
                tool="aws_get_ec2_health",
                kind=ToolKind.READ,
                data={"instances": items},
                source_reference="aws://ec2/describe-instance-status",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"aws_get_ec2_health failed: {e}") from e

    async def aws_get_nlb_target_health(self, target_group_arn: str) -> ToolResult:
        try:
            resp = self._elbv2.describe_target_health(TargetGroupArn=target_group_arn)
            targets = [
                {
                    "target_id": t["Target"]["Id"],
                    "port": t["Target"].get("Port"),
                    "health": t["TargetHealth"]["State"],
                    "reason": t["TargetHealth"].get("Reason"),
                }
                for t in resp.get("TargetHealthDescriptions", [])
            ]
            return ToolResult(
                tool="aws_get_nlb_target_health",
                kind=ToolKind.READ,
                data={"targets": targets, "target_group_arn": target_group_arn},
                source_reference=f"aws://elbv2/target-health/{target_group_arn}",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"aws_get_nlb_target_health failed: {e}") from e

    async def aws_check_s3_backups(
        self, bucket: str, prefix: str = "", max_keys: int = 10
    ) -> ToolResult:
        try:
            resp = self._s3.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=max_keys
            )
            objects = [
                {
                    "key": o["Key"],
                    "size": o["Size"],
                    "last_modified": str(o["LastModified"]),
                }
                for o in resp.get("Contents", [])
            ]
            return ToolResult(
                tool="aws_check_s3_backups",
                kind=ToolKind.READ,
                data={"bucket": bucket, "prefix": prefix, "objects": objects},
                source_reference=f"aws://s3/{bucket}/{prefix}",
                fetched_at=_now(),
            )
        except Exception as e:
            raise MCPConnectionError(f"aws_check_s3_backups failed: {e}") from e
