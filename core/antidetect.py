import random
import asyncio


async def random_point(page, locator):
    """Click at a random point within an element's bounding box instead of center."""
    box = await locator.bounding_box()
    if not box:
        await locator.click()
        return
    width = box["width"]
    height = box["height"]
    # Random offset within the element (avoid extreme edges)
    rand_x = box["x"] + random.uniform(width * 0.15, width * 0.85)
    rand_y = box["y"] + random.uniform(height * 0.15, height * 0.85)
    await page.mouse.click(rand_x, rand_y)


async def random_point_right_part(page, locator):
    """Click at a random point in the right half of an element."""
    box = await locator.bounding_box()
    if not box:
        await locator.click()
        return
    width = box["width"]
    height = box["height"]
    rand_x = box["x"] + random.uniform(width * 0.5, width * 0.85)
    rand_y = box["y"] + random.uniform(height * 0.15, height * 0.85)
    await page.mouse.click(rand_x, rand_y)


async def human_delay(min_ms: int = 200, max_ms: int = 800):
    """Random delay to simulate human-like timing."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(delay)


async def typing_delay(page, selector: str, text: str):
    """Type text with random per-character delays like a human."""
    element = page.locator(selector)
    await element.click()
    await asyncio.sleep(random.uniform(0.1, 0.3))
    for char in text:
        await page.keyboard.type(char, delay=random.uniform(30, 120))
    await asyncio.sleep(random.uniform(0.1, 0.3))


def adjust_stake_for_line_movement(original_stake: float, given_line: float,
                                    actual_line: float, tip_direction: str,
                                    goal_scored: bool = False) -> float:
    """
    Adjust bet amount based on how the line has moved since the tip was given.
    Mirrors CopytipBot's line movement logic.
    """
    diff = abs(actual_line - given_line)

    if tip_direction.lower() == "over":
        if actual_line > given_line:
            # Line moved up (worse for over)
            if goal_scored:
                return original_stake  # Goal scored, line expected to move
            if diff >= 0.75:
                return original_stake * 0.05
            elif diff >= 0.5:
                return original_stake * 0.10
            elif diff >= 0.25:
                return original_stake * 0.75
    elif tip_direction.lower() == "under":
        if actual_line < given_line:
            # Line moved down (worse for under)
            if goal_scored:
                return original_stake
            if diff >= 0.75:
                return original_stake * 0.05
            elif diff >= 0.5:
                return original_stake * 0.10
            elif diff >= 0.25:
                return original_stake * 0.75

    return original_stake


def adjust_stake_for_score(original_stake: float, tip_direction: str,
                           tipped_team_scored: bool) -> float:
    """Adjust stake based on whether tipped or opposing team scored."""
    if tipped_team_scored:
        return original_stake * 0.5
    else:
        return original_stake * 1.5


def stagger_delay(min_sec: int, max_sec: int) -> float:
    """Generate a random stagger delay for multi-profile bet placement."""
    return random.uniform(min_sec, max_sec)
