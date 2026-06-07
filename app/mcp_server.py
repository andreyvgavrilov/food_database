from __future__ import annotations

from typing import Any, Callable

from app.agent.tools import build_agent_tools
from app.config import Settings, load_settings


MCP_SERVER_NAME = "AI Nutrition Agent"


def create_mcp_server(settings: Settings | None = None, mcp_factory: Callable[[str], Any] | None = None) -> Any:
    """Create an MCP server exposing the same nutrition tools used by the agent."""
    resolved_settings = settings or load_settings()
    if mcp_factory is None:
        from mcp.server.fastmcp import FastMCP

        mcp_factory = FastMCP

    mcp = mcp_factory(MCP_SERVER_NAME)
    lookup_tool, calculator_tool = build_agent_tools(resolved_settings)

    @mcp.tool()
    def get_ingredient_nutrition(
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Get USDA nutrition data and portion conversions for one standard English ingredient."""
        return lookup_tool(
            ingredient_name=ingredient_name,
            preferred_food_category=preferred_food_category,
            max_results=max_results,
        )

    @mcp.tool()
    def calculate_total_nutrition(
        ingredients: list[dict[str, Any]],
        servings: float | None = None,
    ) -> dict[str, Any]:
        """Calculate per-ingredient, total, per-100g, and optional per-serving nutrition for a recipe."""
        return calculator_tool(ingredients=ingredients, servings=servings)

    return mcp


def main() -> None:
    create_mcp_server().run()


if __name__ == "__main__":
    main()
