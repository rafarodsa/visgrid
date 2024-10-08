import copy
from typing import Tuple, Union, Optional

import numpy as np
from gym import spaces

from .gridworld import GridworldEnv
from .components import Passenger, Depot
from .. import utils

class TaxiEnv(GridworldEnv):
    INTERACT = 5

    dimensions_onehot = {
        'wall_width': 1,
        'cell_width': 1,
        'character_width': 1,
        'depot_width': 1,
        'border_widths': (0, 0),
        'dash_width': 1,
    }
    dimensions_5x5_to_48x48 = {
        'wall_width': 1,
        'cell_width': 7,
        'character_width': 3,
        'depot_width': 1,
        'border_widths': (4, 3),
        'dash_width': 4,
    }
    dimensions_5x5_to_64x64 = {
        'wall_width': 1,
        'cell_width': 11,
        'character_width': 7,
        'depot_width': 2,
        'border_widths': (2, 1),
        'dash_width': 4,
    }
    dimensions_5x5_to_84x84 = {
        'wall_width': 2,
        'cell_width': 13,
        'character_width': 9,
        'depot_width': 3,
        'border_widths': (4, 3),
        'dash_width': 6,
    }
    dimensions_10x10_to_128x128 = copy.copy(dimensions_5x5_to_64x64)
    dimensions_10x10_to_128x128.update({
        'border_widths': (4, 3),
    })

    def __init__(self,
                 size: int = 5,
                 n_passengers: int = 1,
                 exploring_starts: bool = True,
                 terminate_on_goal: bool = True,
                 fixed_goal: bool = False,
                 depot_dropoff_only: bool = False,
                 should_render: bool = True,
                 render_fast: bool = False,
                 dimensions: dict = None):
        """
        Visual taxi environment

        Original 5x5 taxi environment adapted from:
            Dietterich, G. Thomas. "Hierarchical Reinforcement Learning
            with the MAXQ Value Function Decomposition", JAIR, 2000

        Extended 10x10 version adapted from:
            Diuk, Cohen, & Littman. "An Object-Oriented Representation
            for Efficient Reinforcement Learning", ICML, 2008

        size: {5, 10}
        n_passengers: {0..3} for size 5; {0..7} for size 10
        exploring_starts:
            True: initial state is sampled from a balanced distribution over the
                  entire state space.
            False: initial taxi/passenger positions are at random unique depots
        terminate_on_goal:
            True: reaching the goal produces a terminal state and a reward
            False: the goal has no special significance and the episode simply continues
        depot_dropoff_only:
            True: passengers can only be dropped off at (vacant) depots
            False: passengers can be dropped off anywhere in the grid
        should_render:
            True: Observations are images
            False: Observations use internal state vector
        dimensions: dictionary of size information for should_render
        """
        if size not in [5, 10]:
            raise NotImplementedError('size must be in {5, 10}')
        self.size = size
        self.n_passengers = n_passengers
        self.depot_dropoff_only = depot_dropoff_only
        if size == 5:
            self._default_dimensions = self.dimensions_5x5_to_64x64
        elif size == 10:
            self._default_dimensions = self.dimensions_10x10_to_128x128
        super().__init__(rows=size,
                         cols=size,
                         exploring_starts=exploring_starts,
                         terminate_on_goal=terminate_on_goal,
                         fixed_goal=fixed_goal,
                         hidden_goal=False,
                         should_render=should_render,
                         render_fast=render_fast,
                         dimensions=dimensions)

        self.goal = None
        self._initialize_walls()
        self._initialize_passengers()
        self._initialize_goal()

        self.action_space = spaces.Discrete(len(self._action_ids)+1)

    # ------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------

    def _initialize_state_space(self):
        taxi_factor_sizes = (self.rows, self.cols)
        psgr_factor_sizes = (self.rows, self.cols, 2, len(self.depots))
        self.factor_sizes = taxi_factor_sizes + (psgr_factor_sizes * self.n_passengers)
        self.state_space = spaces.MultiDiscrete(self.factor_sizes, dtype=int)

    def _initialize_depots(self, _):
        if self.size == 5:
            self.depot_locs = {# yapf: disable
                'red':    (0, 0),
                'yellow': (4, 0),
                'blue':   (4, 3),
                'green':  (0, 4),
            }# yapf: enable
        elif self.size == 10:
            self.depot_locs = {# yapf: disable
                'red':     (0, 0),
                'blue':    (8, 0),
                'green':   (9, 4),
                'yellow':  (0, 5),
                'gray':    (3, 3),
                'magenta': (4, 6),
                'cyan':    (0, 8),
                'orange':  (9, 9),
            }# yapf: enable
        else:
            raise NotImplementedError(
                f'Invalid size ({self.size}) provided for {self.__classname__}'
                'Valid options: {5, 10}.')

        self.depot_names = sorted(self.depot_locs.keys())
        self.depot_ids = {name: id_ for id_, name in enumerate(self.depot_names)}
        self.depots = dict()
        for name in self.depot_names:
            self.depots[name] = Depot(color=name, visible=False)
            self.depots[name].position = self.depot_locs[name]

    def _initialize_walls(self):
        if self.size == 5:
            self.grid[1:4, 4] = 1
            self.grid[7:10, 2] = 1
            self.grid[7:10, 6] = 1
        elif self.size == 10:
            self.grid[1:8, 6] = 1
            self.grid[13:20, 2] = 1
            self.grid[13:20, 8] = 1
            self.grid[5:12, 12] = 1
            self.grid[1:8, 16] = 1
            self.grid[13:20, 16] = 1
        else:
            raise NotImplementedError(
                f'Invalid size ({self.size}) provided for {self.__classname__}'
                'Valid options: {5, 10}.')

    def _initialize_passengers(self):
        self.passenger = None
        max_passengers = len(self.depots) - 1
        if not (0 <= self.n_passengers <= max_passengers):
            raise ValueError(
                f"'n_passengers' ({self.n_passengers}) must be between 0 and {max_passengers}")

        goal_depots = copy.deepcopy(self.depot_names)
        self.np_random.shuffle(goal_depots)
        self.passengers = [Passenger(color=c) for c in goal_depots][:self.n_passengers]

    def _initialize_goal(self):
        self._reset_goal()

    # ------------------------------------------------------------
    # Environment API
    # ------------------------------------------------------------

    def _reset(self):
        if not self.fixed_goal:
            self._reset_goal()

        while True:
            if self.exploring_starts:
                self._reset_exploring_start()
            else:
                self._reset_classic_start()

            s = self.get_state()
            # Repeat until we aren't at a goal state
            if not self._check_goal(s):
                break

    def _reset_goal(self, ):
        # Give passengers random unique goal depots
        goal_depots = copy.deepcopy(self.depot_names)
        self.np_random.shuffle(goal_depots)
        for d in self.depots.values():
            d.visible = False
        for p, g in zip(self.passengers, goal_depots[:self.n_passengers]):
            p.color = g
            self.depots[g].visible = True

    def _reset_classic_start(self):
        # Place passengers at randomly chosen depots
        start_depots = copy.deepcopy(self.depot_names)
        self.np_random.shuffle(start_depots)
        for i, p in enumerate(self.passengers):
            p.position = self.depots[start_depots[i]].position
            p.in_taxi = False

        # Place taxi at a different unique depot
        self.agent.position = self.depots[start_depots[-1]].position
        self.passenger = None

    def _reset_exploring_start(self):
        # Fully randomize passenger locations (without overlap)
        while True:
            passenger_locs = np.stack(
                [self._random_grid_position() for _ in range(self.n_passengers)], axis=0)
            if len(np.unique(passenger_locs, axis=0)) == len(passenger_locs):
                break
        for i, p in enumerate(self.passengers):
            p.position = passenger_locs[i]
            p.in_taxi = False

        # Randomly decide whether to move the taxi to a passenger
        if self.np_random.random() > 0.5:
            # If so, randomly choose which passenger
            p = self.np_random.choice(self.passengers)
            self.agent.position = p.position

            # Randomly decide if that passenger should be *in* the taxi
            if self.np_random.random() > 0.5:
                p.in_taxi = True
                self.passenger = p
            else:
                self.passenger = None
        else:
            # Fully randomize taxi position
            self.agent.position = self._random_grid_position()
            self.passenger = None

    def _step(self, action):
        """
        Execute action without checking if it can run
        """
        if action != self.INTERACT:
            super()._step(action)
            if self.passenger is not None:
                self.passenger.position = self.agent.position
        else:  # Interact
            if self.passenger is None:
                # pick up
                for p in self.passengers:
                    if (self.agent.position == p.position).all():
                        p.in_taxi = True
                        self.passenger = p
                        break  # max one passenger per taxi
            else:
                # dropoff
                dropoff_clear = True
                for p in (p for p in self.passengers if p is not self.passenger):
                    if (p.position == self.passenger.position).all():
                        dropoff_clear = False
                        break
                if dropoff_clear:
                    self.passenger.in_taxi = False
                    self.passenger = None

    def can_run(self, action):
        assert action in range(len(self._action_ids)+1)
        if action < len(self._action_ids):
            # movement
            offset = self._action_offsets[action]
            if self.grid.has_wall(self.agent.position, offset):
                return False
            elif self.passenger is None:
                return True
            else:
                # ensure movement won't cause passengers to overlap
                next_position = (self.agent.position + offset)
                for p in self.passengers:
                    if (p is not self.passenger) and (next_position == p.position).all():
                        return False
                return True
        else:
            if self.passenger is None:
                # pickup; can only pick up a passenger if one is here
                for p in self.passengers:
                    if (self.agent.position == p.position).all():
                        return True
                return False
            else:
                # dropoff
                if not self.depot_dropoff_only:
                    return True
                elif any([(depot.position == self.agent.position).all()
                          for depot in self.depots.values()]):
                    return True
                return False

    def get_state(self) -> np.ndarray:
        state = []
        row, col = self.agent.position
        state.extend([row, col])
        for p in self.passengers:
            row, col = p.position
            goal_depot_id = self.depot_ids[p.color]
            state.extend([row, col, p.in_taxi, goal_depot_id])
        return np.asarray(state, dtype=int)

    def set_state(self, state: Union[Tuple, np.ndarray]):
        row, col, *remaining = state
        self.agent.position = row, col
        self.passenger = None
        self.passengers = []
        while remaining:
            row, col, in_taxi, goal_depot_id, *remaining = remaining
            color = self.depot_names[goal_depot_id]
            p = Passenger((row, col), color)
            p.in_taxi = in_taxi
            if in_taxi:
                self.passenger = p
            self.passengers.append(p)

    def is_valid_pos(self, pos):
        taxi_row, taxi_col, psgr_row, psgr_col, in_taxi, goal_idx = pos
        if not in_taxi:
            return True
        elif (taxi_row == psgr_row) and (taxi_col == psgr_col):
            return True
        return False

    def get_goal_state(self) -> np.ndarray:
        state = []
        # omit taxi position from goal state
        for p in self.passengers:
            goal_depot_name = p.color
            goal_depot_id = self.depot_ids[goal_depot_name]
            goal_row, goal_col = self.depots[goal_depot_name].position
            in_taxi = False
            state.extend([goal_row, goal_col, in_taxi, goal_depot_id])
        return np.asarray(state, dtype=int)

    def _check_goal(self, state=None):
        if state is None:
            state = self.get_state()
        goal = self.get_goal_state()
        if np.all(state[2:] == goal):  # ignore taxi, check passenger positions
            return True
        else:
            return False

    # ------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------

    def _render_objects(self) -> dict:
        objects = super()._render_objects()
        del objects['agent']

        passenger_patches = np.zeros_like(objects['walls'])
        for p in self.passengers:
            if not p.in_taxi or not self.render_fast:
                patch = self._render_passenger_patch(p.in_taxi, p.color)
                self._add_patch(passenger_patches, patch, p.position)

        taxi_patches = np.zeros_like(objects['walls'])
        patch = self._render_taxi_patch()
        self._add_patch(taxi_patches, patch, self.agent.position)

        objects.update({
            'taxi': taxi_patches,
            'passengers': passenger_patches,
        })

        return objects

    def _render_frame(self, content):
        """Generate a border to reflect the current in_taxi status"""
        if self.render_fast:
            return content
        in_taxi = (self.passenger is not None)
        img_shape = self.dimensions['img_shape']
        dw = self.dimensions['dash_width']
        if in_taxi:
            # pad with dashes to HxW
            checker_tile = np.block([
                [np.ones((dw, dw)), np.zeros((dw, dw))],
                [np.zeros((dw, dw)), np.ones((dw, dw))],
            ])
            pad_width = np.array(img_shape) - checker_tile.shape
            pad_width = tuple(zip((0, 0), pad_width))
            image = np.pad(checker_tile, pad_width, mode='wrap')

            # convert to color HxWx3
            image = np.tile(np.expand_dims(image, -1), (1, 1, 3))
            image = image * utils.get_rgb(self.passenger.color)
        else:
            # pad with white to HxWx3
            image = np.ones(img_shape + (3, ))

        pad_top_left, pad_bot_right = self.dimensions['border_widths']
        pad_width = ((pad_top_left, pad_bot_right), (pad_top_left, pad_bot_right), (0, 0))
        assert image.shape == np.pad(content, pad_width=pad_width).shape

        return image

    def _render_passenger_patch(self, in_taxi, color):
        """Generate a patch representing a passenger, along with any associated marks"""
        if self.render_fast:
            return np.array([[[0, 1, 0]]])
        cell_width = self.dimensions['cell_width']

        patch = self._render_character_patch(color='white')

        # add marks relating to 'in_taxi'
        center = cell_width // 2
        if in_taxi:
            marks = np.zeros_like(patch[:, :, 0])
            marks[center, :] = 1
            marks[:, center] = 1
        else:
            marks = np.eye(cell_width, dtype=int) | np.fliplr(np.eye(cell_width, dtype=int))
        marks[(patch == 0).max(axis=-1)] = 0

        patch = utils.to_rgb(patch, color)
        patch[marks > 0, :] = utils.get_rgb('dimgray') / 4

        return patch

    def _render_taxi_patch(self):
        """Generate a patch representing a taxi"""
        if self.render_fast:
            return np.array([[[1, 0, 0]]])
        depot = self._render_depot_patch(color='white')
        passenger = self._render_character_patch('white')
        patch = np.ones_like(depot) - (depot + passenger)

        # crop edges
        patch[0, :, :] = 0
        patch[:, 0, :] = 0
        patch[-1, :, :] = 0
        patch[:, -1, :] = 0

        patch = patch * utils.get_rgb('dimgray') / 4

        return patch
