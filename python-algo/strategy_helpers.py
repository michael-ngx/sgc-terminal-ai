"""
Strategy helper functions for C1 Terminal algo development.

These helpers build on top of the gamelib API to provide higher-level
analysis and decision-making utilities. Import them in algo_strategy.py:

    from strategy_helpers import StrategyHelpers

Then instantiate with your config in on_game_start:

    self.helpers = StrategyHelpers(config)

And use in on_turn:

    self.helpers.find_weakest_attack_path(game_state)
"""

import math
import copy
from sys import maxsize

import gamelib


class StrategyHelpers:
    """Collection of reusable strategy helpers for C1 Terminal."""

    def __init__(self, config):
        self.config = config
        self.WALL = config["unitInformation"][0]["shorthand"]
        self.SUPPORT = config["unitInformation"][1]["shorthand"]
        self.TURRET = config["unitInformation"][2]["shorthand"]
        self.SCOUT = config["unitInformation"][3]["shorthand"]
        self.DEMOLISHER = config["unitInformation"][4]["shorthand"]
        self.INTERCEPTOR = config["unitInformation"][5]["shorthand"]
        self.SP = 0
        self.MP = 1
        self.ARENA_SIZE = 28
        self.HALF_ARENA = 14

    # ------------------------------------------------------------------ #
    #  MAP SCANNING & UNIT QUERIES
    # ------------------------------------------------------------------ #

    def get_friendly_structures(self, game_state, unit_type=None):
        """Return a list of (unit, [x, y]) for all friendly structures.

        Args:
            game_state: The current GameState
            unit_type: Optional filter – one of WALL / TURRET / SUPPORT

        Returns:
            List of (GameUnit, [x, y]) tuples
        """
        results = []
        for location in game_state.game_map:
            for unit in game_state.game_map[location]:
                if unit.player_index == 0 and unit.stationary:
                    if unit_type is None or unit.unit_type == unit_type:
                        results.append((unit, [unit.x, unit.y]))
        return results

    def get_enemy_structures(self, game_state, unit_type=None):
        """Return a list of (unit, [x, y]) for all enemy structures.

        Args:
            game_state: The current GameState
            unit_type: Optional filter – one of WALL / TURRET / SUPPORT

        Returns:
            List of (GameUnit, [x, y]) tuples
        """
        results = []
        for location in game_state.game_map:
            for unit in game_state.game_map[location]:
                if unit.player_index == 1 and unit.stationary:
                    if unit_type is None or unit.unit_type == unit_type:
                        results.append((unit, [unit.x, unit.y]))
        return results

    def count_enemy_structures_in_area(self, game_state, unit_type=None,
                                       x_range=None, y_range=None):
        """Count enemy structures in a rectangular region of the map.

        Args:
            game_state: The current GameState
            unit_type: Optional unit-type filter (WALL, TURRET, SUPPORT, or None for all)
            x_range: Optional (min_x, max_x) tuple, inclusive
            y_range: Optional (min_y, max_y) tuple, inclusive

        Returns:
            Integer count of matching enemy structures
        """
        count = 0
        for unit, loc in self.get_enemy_structures(game_state, unit_type):
            if x_range and not (x_range[0] <= loc[0] <= x_range[1]):
                continue
            if y_range and not (y_range[0] <= loc[1] <= y_range[1]):
                continue
            count += 1
        return count

    def get_damaged_structures(self, game_state, health_pct=0.5):
        """Find friendly structures below a health percentage threshold.

        Args:
            game_state: The current GameState
            health_pct: Fraction of max_health (0.0–1.0). Default 0.5 (50 %)

        Returns:
            List of (GameUnit, [x, y]) sorted worst-health-first
        """
        damaged = []
        for unit, loc in self.get_friendly_structures(game_state):
            if unit.health < unit.max_health * health_pct:
                damaged.append((unit, loc))
        damaged.sort(key=lambda t: t[0].health / t[0].max_health)
        return damaged

    # ------------------------------------------------------------------ #
    #  PATH & DAMAGE ANALYSIS
    # ------------------------------------------------------------------ #

    def estimate_path_damage(self, game_state, path):
        """Estimate total damage a friendly mobile unit would take along *path*.

        For each tile in the path, sums up the damage from every enemy turret
        that can reach that tile.

        Args:
            game_state: The current GameState
            path: List of [x, y] locations (as returned by find_path_to_edge)

        Returns:
            Float – total estimated damage along the path
        """
        if not path:
            return maxsize
        damage = 0
        for loc in path:
            attackers = game_state.get_attackers(loc, 0)
            for attacker in attackers:
                damage += attacker.damage_i
        return damage

    def estimate_structures_on_path(self, game_state, path, player_index=1):
        """Count how many structures belonging to *player_index* are adjacent to *path*.

        Useful for gauging how much a Demolisher could destroy while walking.

        Args:
            game_state: The current GameState
            path: List of [x, y]
            player_index: 0 = friendly, 1 = enemy (default)

        Returns:
            Integer count of distinct structures in attack range of at least one path tile
        """
        demolisher_unit = gamelib.GameUnit(self.DEMOLISHER, self.config)
        attack_range = demolisher_unit.attackRange
        seen = set()
        for loc in path:
            targets_in_range = game_state.game_map.get_locations_in_range(loc, attack_range)
            for tloc in targets_in_range:
                for unit in game_state.game_map[tloc]:
                    if unit.stationary and unit.player_index == player_index:
                        seen.add((tloc[0], tloc[1]))
        return len(seen)

    def find_weakest_attack_path(self, game_state, unit_type=None):
        """Test every friendly edge spawn point and return the one whose
        path to the enemy edge takes the least estimated damage.

        Args:
            game_state: The current GameState
            unit_type: Unused today but reserved for future per-unit range tweaks

        Returns:
            (best_location, best_path, min_damage) tuple
        """
        edges = (
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) +
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        )
        best_location = None
        best_path = None
        min_damage = maxsize

        for loc in edges:
            if game_state.contains_stationary_unit(loc):
                continue
            path = game_state.find_path_to_edge(loc)
            if not path:
                continue
            damage = self.estimate_path_damage(game_state, path)
            if damage < min_damage:
                min_damage = damage
                best_path = path
                best_location = loc

        return best_location, best_path, min_damage

    def rank_spawn_locations(self, game_state, locations):
        """Rank a list of spawn locations by estimated path damage (ascending).

        Args:
            game_state: The current GameState
            locations: List of [x, y] spawn locations to evaluate

        Returns:
            List of (location, damage) tuples sorted safest-first
        """
        scored = []
        for loc in locations:
            if game_state.contains_stationary_unit(loc):
                continue
            path = game_state.find_path_to_edge(loc)
            damage = self.estimate_path_damage(game_state, path)
            scored.append((loc, damage))
        scored.sort(key=lambda t: t[1])
        return scored

    def path_reaches_edge(self, game_state, start_location):
        """Check whether a unit spawned at *start_location* would reach an
        enemy edge (i.e., is NOT a self-destruct path).

        Args:
            game_state: The current GameState
            start_location: [x, y]

        Returns:
            Boolean
        """
        path = game_state.find_path_to_edge(start_location)
        if not path:
            return False
        target_edge = game_state.get_target_edge(start_location)
        edge_locs = game_state.game_map.get_edge_locations(target_edge)
        return path[-1] in edge_locs

    # ------------------------------------------------------------------ #
    #  DEFENSE ANALYSIS
    # ------------------------------------------------------------------ #

    def get_turret_coverage(self, game_state, player_index=0):
        """Build a dict mapping each arena tile to the number of turrets
        belonging to *player_index* that can hit it.

        Args:
            game_state: The current GameState
            player_index: 0 = your turrets, 1 = enemy turrets

        Returns:
            dict  {(x, y): int}  – tiles with zero coverage are omitted
        """
        coverage = {}
        turrets = []
        for location in game_state.game_map:
            for unit in game_state.game_map[location]:
                if unit.unit_type == self.TURRET and unit.player_index == player_index:
                    turrets.append(unit)

        for turret in turrets:
            locs = game_state.game_map.get_locations_in_range(
                [turret.x, turret.y], turret.attackRange
            )
            for loc in locs:
                key = (loc[0], loc[1])
                coverage[key] = coverage.get(key, 0) + 1
        return coverage

    def find_uncovered_friendly_edges(self, game_state):
        """Return friendly edge locations that are NOT covered by any of
        your own turrets.  These are vulnerable entry points the enemy
        might exploit.

        Returns:
            List of [x, y] locations
        """
        coverage = self.get_turret_coverage(game_state, player_index=0)
        edges = (
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) +
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        )
        uncovered = [loc for loc in edges if (loc[0], loc[1]) not in coverage]
        return uncovered

    def find_weak_defense_columns(self, game_state, y_rows=None):
        """Identify x-columns on your side where turret coverage is thinnest.

        Scans the given rows (default: y = 10–13, the front of your base) and
        returns columns sorted by ascending total coverage.

        Args:
            game_state: The current GameState
            y_rows: Iterable of y values to scan (default range(10, 14))

        Returns:
            List of (x, total_coverage) sorted weakest-first
        """
        if y_rows is None:
            y_rows = range(10, 14)
        coverage = self.get_turret_coverage(game_state, player_index=0)
        column_coverage = {}
        for y in y_rows:
            for x in range(self.ARENA_SIZE):
                if game_state.game_map.in_arena_bounds([x, y]):
                    column_coverage[x] = column_coverage.get(x, 0) + coverage.get((x, y), 0)
        result = sorted(column_coverage.items(), key=lambda t: t[1])
        return result

    # ------------------------------------------------------------------ #
    #  RESOURCE & ECONOMY HELPERS
    # ------------------------------------------------------------------ #

    def can_afford(self, game_state, unit_type, count=1, upgrade=False):
        """Check whether you can afford *count* units of *unit_type*.

        Args:
            game_state: The current GameState
            unit_type: WALL, TURRET, SUPPORT, SCOUT, etc.
            count: How many units
            upgrade: If True, check upgrade cost instead

        Returns:
            Boolean
        """
        costs = game_state.type_cost(unit_type, upgrade)
        resources = game_state.get_resources()
        return (resources[self.SP] >= costs[self.SP] * count and
                resources[self.MP] >= costs[self.MP] * count)

    def sp_after_refund(self, game_state, locations):
        """Estimate SP you'd gain if you removed structures at *locations*
        (75 % refund of original SP cost, as defined in config).

        Args:
            game_state: The current GameState
            locations: List of [x, y]

        Returns:
            Float – total SP refunded
        """
        refund = 0
        for loc in locations:
            unit = game_state.contains_stationary_unit(loc)
            if unit and unit.player_index == 0:
                pct = self.config["unitInformation"][0].get("refundPercentage", 0.75)
                refund += unit.cost[self.SP] * pct
        return refund

    def estimate_enemy_mp(self, game_state, turns_ahead=1):
        """Predict enemy MP in *turns_ahead* turns.

        Args:
            game_state: The current GameState
            turns_ahead: How many turns to project

        Returns:
            Float – estimated enemy MP
        """
        return game_state.project_future_MP(
            turns_in_future=turns_ahead,
            player_index=1,
            current_MP=game_state.get_resource(self.MP, 1),
        )

    # ------------------------------------------------------------------ #
    #  ATTACK DECISION HELPERS
    # ------------------------------------------------------------------ #

    def should_attack(self, game_state, mp_threshold=None, damage_threshold=None):
        """Heuristic: decide whether it is a good turn to send mobile units.

        Criteria (all must pass when specified):
        - You have at least *mp_threshold* MP  (default: 10)
        - The safest path takes less than *damage_threshold* total damage (default: 100)

        Args:
            game_state: The current GameState
            mp_threshold: Minimum MP to consider attacking (default 10)
            damage_threshold: Maximum acceptable path damage (default 100)

        Returns:
            Boolean
        """
        if mp_threshold is None:
            mp_threshold = 10
        if damage_threshold is None:
            damage_threshold = 100

        if game_state.get_resource(self.MP) < mp_threshold:
            return False

        _, _, min_damage = self.find_weakest_attack_path(game_state)
        return min_damage <= damage_threshold

    def scout_rush_value(self, game_state, location):
        """Estimate the "value" of a Scout rush from *location*.

        Value = number of scouts affordable × (1 if path reaches edge, 0 otherwise)
                minus estimated deaths along the path.

        Args:
            game_state: The current GameState
            location: [x, y] spawn point

        Returns:
            Float – higher is better; negative means the rush is likely unprofitable
        """
        num_scouts = game_state.number_affordable(self.SCOUT)
        if num_scouts == 0:
            return -1

        path = game_state.find_path_to_edge(location)
        if not path:
            return -1

        damage = self.estimate_path_damage(game_state, path)
        scout_hp = gamelib.GameUnit(self.SCOUT, self.config).max_health
        estimated_deaths = damage / scout_hp if scout_hp > 0 else num_scouts
        survivors = max(0, num_scouts - estimated_deaths)

        # Bonus if path reaches the edge
        target_edge = game_state.get_target_edge(location)
        edge_locs = game_state.game_map.get_edge_locations(target_edge)
        reaches = path[-1] in edge_locs
        if not reaches:
            survivors *= 0.3  # self-destruct is much less valuable

        return survivors

    def best_scout_rush_location(self, game_state):
        """Find the spawn location that maximises scout rush value.

        Returns:
            (location, value) tuple, or (None, -1) if nothing viable
        """
        edges = (
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) +
            game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        )
        best_loc = None
        best_val = -1
        for loc in edges:
            if game_state.contains_stationary_unit(loc):
                continue
            val = self.scout_rush_value(game_state, loc)
            if val > best_val:
                best_val = val
                best_loc = loc
        return best_loc, best_val

    def demolisher_value(self, game_state, location):
        """Estimate how many enemy structures a Demolisher line from *location*
        could threaten.

        Args:
            game_state: The current GameState
            location: [x, y] spawn point

        Returns:
            Integer – number of distinct enemy structures in attack range along the path
        """
        path = game_state.find_path_to_edge(location)
        if not path:
            return 0
        return self.estimate_structures_on_path(game_state, path, player_index=1)

    # ------------------------------------------------------------------ #
    #  BUILD PLAN HELPERS
    # ------------------------------------------------------------------ #

    def prioritized_build(self, game_state, build_plan):
        """Place structures from a priority-ordered build plan, spending
        available SP top-to-bottom.

        Args:
            game_state: The current GameState
            build_plan: list of (unit_type, [x, y]) tuples in priority order.
                        Optionally a 3-tuple (unit_type, [x, y], upgrade) where
                        upgrade is a bool.

        Returns:
            Number of units successfully placed or upgraded
        """
        placed = 0
        for entry in build_plan:
            if len(entry) == 3:
                utype, loc, upgrade = entry
            else:
                utype, loc = entry
                upgrade = False

            if upgrade:
                placed += game_state.attempt_upgrade(loc)
            else:
                placed += game_state.attempt_spawn(utype, loc)
        return placed

    def build_wall_line(self, game_state, y, x_start, x_end, upgrade=False):
        """Build a row of walls from x_start to x_end at row y.

        Args:
            game_state: The current GameState
            y: The y-coordinate for the wall line
            x_start: Starting x (inclusive)
            x_end: Ending x (inclusive)
            upgrade: If True, also upgrade placed walls

        Returns:
            Number of walls placed
        """
        locations = []
        step = 1 if x_end >= x_start else -1
        for x in range(x_start, x_end + step, step):
            if game_state.game_map.in_arena_bounds([x, y]):
                locations.append([x, y])
        placed = game_state.attempt_spawn(self.WALL, locations)
        if upgrade:
            game_state.attempt_upgrade(locations)
        return placed

    def mirror_locations(self, locations):
        """Mirror a list of locations across the vertical center line (x = 13.5).

        Useful for building symmetrical defenses.

        Args:
            locations: List of [x, y]

        Returns:
            List of mirrored [x, y] locations
        """
        mirrored = []
        for loc in locations:
            mx = self.ARENA_SIZE - 1 - loc[0]
            mirrored.append([mx, loc[1]])
        return mirrored

    def symmetric_build(self, game_state, unit_type, half_locations, upgrade=False):
        """Build units at *half_locations* AND their mirror, creating a
        symmetric defense.

        Args:
            game_state: The current GameState
            unit_type: WALL / TURRET / SUPPORT
            half_locations: List of [x, y] on one side (x < 14 recommended)
            upgrade: Also upgrade after placing

        Returns:
            Total units placed
        """
        full = half_locations + self.mirror_locations(half_locations)
        placed = game_state.attempt_spawn(unit_type, full)
        if upgrade:
            game_state.attempt_upgrade(full)
        return placed

    def repair_damaged(self, game_state, health_pct=0.35):
        """Remove and rebuild any friendly structures whose health has
        dropped below *health_pct* of their max.

        This uses the remove-and-rebuild pattern: on this turn the
        structure is flagged for removal, and on the next turn it gets
        rebuilt. SP is refunded at the configured percentage.

        Args:
            game_state: The current GameState
            health_pct: Threshold (0.0–1.0)

        Returns:
            Number of structures flagged for removal
        """
        removed = 0
        for unit, loc in self.get_damaged_structures(game_state, health_pct):
            game_state.attempt_remove(loc)
            removed += 1
        return removed

    # ------------------------------------------------------------------ #
    #  ACTION-FRAME ANALYSIS
    # ------------------------------------------------------------------ #

    @staticmethod
    def parse_action_frame(turn_string):
        """Parse an action-frame JSON string and return structured events.

        Args:
            turn_string: Raw JSON string from the game engine

        Returns:
            dict with keys: 'breaches', 'damage', 'deaths', 'attacks', 'spawns', 'shields'
            Each value is a list of raw event data from that frame.
        """
        import json
        state = json.loads(turn_string)
        events = state.get("events", {})
        return {
            "breaches": events.get("breach", []),
            "damage": events.get("damage", []),
            "deaths": events.get("death", []),
            "attacks": events.get("attack", []),
            "spawns": events.get("spawn", []),
            "shields": events.get("shield", []),
            "self_destructs": events.get("selfDestruct", []),
            "melee": events.get("melee", []),
        }

    @staticmethod
    def breach_locations_from_frame(turn_string, only_enemy_scoring=True):
        """Extract breach locations from an action frame.

        Args:
            turn_string: Raw JSON string
            only_enemy_scoring: If True (default), only return locations where
                                the *enemy* scored on *you*.

        Returns:
            List of [x, y] locations where breaches occurred
        """
        import json
        state = json.loads(turn_string)
        breaches = state.get("events", {}).get("breach", [])
        locations = []
        for b in breaches:
            loc = b[0]
            # In raw frame data, owner 1 = you, 2 = opponent
            unit_owner_self = b[4] == 1
            if only_enemy_scoring and unit_owner_self:
                continue
            if not only_enemy_scoring or not unit_owner_self:
                locations.append(loc)
        return locations

    # ------------------------------------------------------------------ #
    #  MISC UTILITIES
    # ------------------------------------------------------------------ #

    def locations_in_row(self, y):
        """Return all valid arena locations in a given row.

        Args:
            y: The row number (0–27)

        Returns:
            List of [x, y] within the arena diamond
        """
        locs = []
        for x in range(self.ARENA_SIZE):
            # Replicates the diamond-bounds check from GameMap
            half = self.HALF_ARENA
            if y < half:
                row_size = y + 1
            else:
                row_size = (self.ARENA_SIZE - 1 - y) + 1
            startx = half - row_size
            endx = startx + (2 * row_size) - 1
            if startx <= x <= endx:
                locs.append([x, y])
        return locs

    def locations_in_column(self, x):
        """Return all valid arena locations in a given column.

        Args:
            x: The column number (0–27)

        Returns:
            List of [x, y] within the arena diamond
        """
        locs = []
        for y in range(self.ARENA_SIZE):
            half = self.HALF_ARENA
            if y < half:
                row_size = y + 1
            else:
                row_size = (self.ARENA_SIZE - 1 - y) + 1
            startx = half - row_size
            endx = startx + (2 * row_size) - 1
            if startx <= x <= endx:
                locs.append([x, y])
        return locs

    def locations_in_friendly_half(self):
        """Return all valid arena locations on your side (y < 14)."""
        locs = []
        for y in range(self.HALF_ARENA):
            locs.extend(self.locations_in_row(y))
        return locs

    def locations_in_enemy_half(self):
        """Return all valid arena locations on the enemy side (y >= 14)."""
        locs = []
        for y in range(self.HALF_ARENA, self.ARENA_SIZE):
            locs.extend(self.locations_in_row(y))
        return locs

    def empty_friendly_locations(self, game_state):
        """Return all locations on your side that have no structure.

        Useful for finding open spots to place new defenses.

        Returns:
            List of [x, y]
        """
        return [
            loc for loc in self.locations_in_friendly_half()
            if not game_state.contains_stationary_unit(loc)
        ]

    def enemy_total_firepower(self, game_state):
        """Sum up the total per-frame damage output of all enemy turrets.

        Returns:
            Float – combined damage_i of all enemy turrets
        """
        total = 0
        for unit, loc in self.get_enemy_structures(game_state, self.TURRET):
            total += unit.damage_i
        return total

    def friendly_total_firepower(self, game_state):
        """Sum up the total per-frame damage output of all your turrets.

        Returns:
            Float – combined damage_i of all your turrets
        """
        total = 0
        for unit, loc in self.get_friendly_structures(game_state, self.TURRET):
            total += unit.damage_i
        return total

    def filter_blocked_locations(self, locations, game_state):
        """Remove locations that contain a stationary unit.

        Args:
            locations: List of [x, y]
            game_state: Current GameState

        Returns:
            Filtered list with only non-blocked locations
        """
        return [loc for loc in locations
                if not game_state.contains_stationary_unit(loc)]

    def is_left_side(self, location):
        """Check if a location is on the left side of the arena (x < 14)."""
        return location[0] < self.HALF_ARENA

    def is_right_side(self, location):
        """Check if a location is on the right side of the arena (x >= 14)."""
        return location[0] >= self.HALF_ARENA

    def corner_locations(self, player="friendly"):
        """Get the four corner locations for the given player.

        Args:
            player: 'friendly' or 'enemy'

        Returns:
            List of [x, y] corner tiles
        """
        if player == "friendly":
            return [[0, 13], [27, 13], [13, 0], [14, 0]]
        else:
            return [[0, 14], [27, 14], [13, 27], [14, 27]]
