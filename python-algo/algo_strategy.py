import gamelib
import random
import math
import warnings
from sys import maxsize
import json


"""
Most of the algo code you write will be in this file unless you create new
modules yourself. Start by modifying the 'on_turn' function.

Advanced strategy tips: 

  - You can analyze action frames by modifying on_action_frame function

  - The GameState.map object can be manually manipulated to create hypothetical 
  board states. Though, we recommended making a copy of the map to preserve 
  the actual current map state.
"""

class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

    def on_game_start(self, config):
        """ 
        Read in config and perform any initial setup here 
        """
        gamelib.debug_write('Configuring your custom algo strategy...')
        self.config = config
        global WALL, FACTORY, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP
        WALL = config["unitInformation"][0]["shorthand"]
        FACTORY = config["unitInformation"][1]["shorthand"]
        TURRET = config["unitInformation"][2]["shorthand"]
        SCOUT = config["unitInformation"][3]["shorthand"]
        DEMOLISHER = config["unitInformation"][4]["shorthand"]
        INTERCEPTOR = config["unitInformation"][5]["shorthand"]
        MP = 1
        SP = 0

        # This is a good place to do initial setup
        # record locations at which we were scored by the enemy
        self.scored_on_locations = []
        # constants for computing effectiveness of attack
        global minGainPerSPSpent, weight_damage_enemy, weight_score
        minGainPerSPSpent = 10
        weight_damage_enemy = 1
        weight_score = 12

    def on_turn(self, turn_state):
        """
        This function is called every turn with the game state wrapper as
        an argument. The wrapper stores the state of the arena and has methods
        for querying its state, allocating your current resources as planned
        unit deployments, and transmitting your intended deployments to the
        game engine.
        """
        game_state = gamelib.GameState(self.config, turn_state)
        gamelib.debug_write('Performing turn {} of your custom algo strategy'.format(game_state.turn_number))
        game_state.suppress_warnings(True)  #Comment or remove this line to enable warnings.

        self.my_strategy(game_state)

        game_state.submit_turn()


    """
    NOTE: All the methods after this point are part of the sample starter-algo
    strategy and can safely be replaced for your custom algo.
    """

    def my_strategy(self, game_state):
        """
        For defense we will use a spread out layout and some interceptors early on.
        We will place turrets near locations the opponent managed to score on.
        For offense we will use long range demolishers if they place stationary units near the enemy's front.
        If there are no stationary units to attack in the front, we will send Scouts to try and score quickly.
        """
        # First, place basic defenses
        self.build_defences(game_state)
        # Now build reactive defenses based on where the enemy scored
        self.build_reactive_defense(game_state)

        #if we have spare SP, let's build some Factories to generate more resources                                                                                                                                                                                                                       
        factory_locations = [[13, 2], [14, 2], [13, 3], [14, 3]]
        game_state.attempt_spawn(FACTORY, factory_locations)
        
        # If the turn is less than 5, stall with interceptors and wait to see enemy's base
        if game_state.turn_number < 3:
            self.stall_with_interceptors(game_state)
        else:
            # Now let's analyze the enemy base to see where their defenses are concentrated.
            # If they have many units in the front we can build a line for our demolishers to attack them at long range.
            if self.detect_enemy_unit(game_state, unit_type=None, valid_x=None, valid_y=[14, 15]) > 10:
                self.demolisher_line_strategy(game_state)
            else:
                # try to attack
                self.attempt_to_attack(game_state)
                
    def attempt_to_attack(self, game_state):
        """
        This function chooses between two types of attacks: all scouts vs. demolisher followed by interceptor
        Gain function of each attack is evaluated. If gain is less than threshold, no attacks will be spawn
        """
        # maximum number of each units for each of the two strategies
        max_scout_spawn = game_state.number_affordable(SCOUT)
        max_interceptor_spawn = game_state.number_affordable(INTERCEPTOR) // 2
        max_demolisher_spawn = game_state.number_affordable(DEMOLISHER) // 2

        # initialize the gains
        scout_gain = -999
        demolisher_gain = -999
        interceptor_gains = [-999, -999]
        # and the location list for interceptor
        # interceptor are sent after demolisher, so the locations should not overlap
        # use the second best if the best one overlaps with the demolisher one
        interceptor_deploy_locations = [[0,0], [0,0]]

        # find available deploy locations on our edge
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        deploy_locations = self.filter_blocked_locations(friendly_edges, game_state)

        # loop over all deploy locations and see how much gain we can get for each strategy: (damage to enemy units + score*12)
        for location in deploy_locations:
            gain_location_scout = self.gain_of_attack(game_state, max_scout_spawn, SCOUT, location)
            gain_location_demolisher = self.gain_of_attack(game_state, max_demolisher_spawn, DEMOLISHER, location)
            gain_location_interceptor = self.gain_of_attack(game_state, max_interceptor_spawn, INTERCEPTOR, location)
            if gain_location_scout > scout_gain:
                scout_deploy_location = location
                scout_gain = gain_location_scout
            if gain_location_demolisher > demolisher_gain:
                demolisher_deploy_location = location
                demolisher_gain = gain_location_demolisher
            if gain_location_interceptor > interceptor_gains[0]:
                interceptor_gains[1] = interceptor_gains[0]
                interceptor_deploy_locations[1] = interceptor_deploy_locations[0]
                interceptor_gains[0] = gain_location_interceptor
                interceptor_deploy_locations[0] = location
            elif gain_location_interceptor > interceptor_gains[1]:
                interceptor_gains[1] = gain_location_interceptor
                interceptor_deploy_locations[1] = location

        # gain divided by the MP spent for the attack
        # attack is ineffective if many MP were spent with little damage dealt to enemy units and low score
        opt1_gain = scout_gain/(game_state.type_cost(SCOUT)[MP] * max_scout_spawn)
        location_index = int(interceptor_deploy_locations[0] == demolisher_deploy_location) # use 0th location for interceptor if it's not overlapping, use the 1st one if it is
        opt2_gain = (demolisher_gain + interceptor_gains[location_index])/(game_state.type_cost(DEMOLISHER)[MP] * max_demolisher_spawn + game_state.type_cost(INTERCEPTOR)[MP] * max_interceptor_spawn)

        # check if the gains per MP spent reach the minimum threshold set
        # compare the two strategies if they both passed the threshold
        if opt1_gain >= minGainPerSPSpent and opt2_gain >= minGainPerSPSpent:
            if opt1_gain >= opt2_gain:
                game_state.attempt_spawn(SCOUT, scout_deploy_location, max_scout_spawn)
            else:
                game_state.attempt_spawn(DEMOLISHER, demolisher_deploy_location, max_demolisher_spawn)
                game_state.attempt_spawn(INTERCEPTOR, interceptor_deploy_locations[location_index], max_interceptor_spawn)
        elif opt1_gain >= minGainPerSPSpent:
            game_state.attempt_spawn(SCOUT, scout_deploy_location, max_scout_spawn)
        elif opt2_gain >= minGainPerSPSpent:
            game_state.attempt_spawn(DEMOLISHER, demolisher_deploy_location, max_demolisher_spawn)
            game_state.attempt_spawn(INTERCEPTOR, interceptor_deploy_locations[location_index], max_interceptor_spawn)
        
    def gain_of_attack(self, game_state, number_units, unit_type, location):
        """
        This function computes the weighted gain of a given type of attack starting at a specific location
        """
        path = game_state.find_path_to_edge(location)
        damage_dealt = 0
        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        unit_class = gamelib.GameUnit(unit_type, game_state.config)
        unit_health = unit_class.health
        unit_range = unit_class.attackRange
        remaining_units = number_units
        total_heath = unit_health * number_units
        for path_location in path:
            num_turrets = len(game_state.get_attackers(path_location, 0))
            for frame_index in range(int(1/(unit_class.speed))):
                total_damage = unit_class.damage_f * remaining_units
                damage_dealt += min(total_damage, self.total_target_health(game_state, path_location, unit_class.attackRange))
                total_heath -= num_turrets * turret_damage
                remaining_units = (total_heath // unit_health) + 1
            return (damage_dealt*weight_damage_enemy + remaining_units*weight_score)
                                    
                                    
    def total_target_health(self, game_state, location, unit_range):
        possible_locations = game_state.game_map.get_locations_in_range(location, unit_range)
        total_health = 0
        for location in possible_locations:
            for enemy_unit in game_state.game_map[location]:
                if enemy_unit.player_index == 0:
                    continue
                else:
                    total_health += enemy_unit.health
        return total_health
            
    def build_defences(self, game_state):
        """
        Build basic defenses using hardcoded locations.
        Remember to defend corners and avoid placing units in the front where enemy demolishers can attack them.
        """
        # Useful tool for setting up your base locations: https://www.kevinbai.design/terminal-map-maker
        # More community tools available at: https://terminal.c1games.com/rules#Download

        # Place turrets that attack enemy units
        turret_locations = [[0, 13], [27, 13], [8, 11], [19, 11], [13, 11], [14, 11]]
        # attempt_spawn will try to spawn units if we have resources, and will check if a blocking unit is already there
        game_state.attempt_spawn(TURRET, turret_locations)
        
        # Place walls in front of turrets to soak up damage for them
        wall_locations = [[8, 12], [19, 12]]
        game_state.attempt_spawn(WALL, wall_locations)
        # upgrade walls so they soak more damage
        game_state.attempt_upgrade(wall_locations)

    def build_reactive_defense(self, game_state):
        """
        This function builds reactive defenses based on where the enemy scored on us from.
        We can track where the opponent scored by looking at events in action frames 
        as shown in the on_action_frame function
        """
        for location in self.scored_on_locations:
            # Build turret one space above so that it doesn't block our own edge spawn locations
            build_location = [location[0], location[1]+1]
            game_state.attempt_spawn(TURRET, build_location)

    def stall_with_interceptors(self, game_state):
        """
        Send out interceptors at random locations to defend our base from enemy moving units.
        """
        # We can spawn moving units on our edges so a list of all our edge locations
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        
        # Remove locations that are blocked by our own structures 
        # since we can't deploy units there.
        deploy_locations = self.filter_blocked_locations(friendly_edges, game_state)
        
        # While we have remaining MP to spend lets send out interceptors randomly.
        while game_state.get_resource(MP) >= game_state.type_cost(INTERCEPTOR)[MP] and len(deploy_locations) > 0:
            # Choose a random deploy location.
            deploy_index = random.randint(0, len(deploy_locations) - 1)
            deploy_location = deploy_locations[deploy_index]
            
            game_state.attempt_spawn(INTERCEPTOR, deploy_location)
            """
            We don't have to remove the location since multiple mobile 
            units can occupy the same space.
            """

    def demolisher_line_strategy(self, game_state):
        """
        Build a line of the cheapest stationary unit so our demolisher can attack from long range.
        """
        # First let's figure out the cheapest unit
        # We could just check the game rules, but this demonstrates how to use the GameUnit class
        stationary_units = [WALL, TURRET, FACTORY]
        unit_costs = [gamelib.GameUnit(unit, game_state.config).cost[game_state.MP] for unit in stationary_units]
        cheapest_unit = stationary_units[unit_costs.index(min(unit_costs))]

        # Now let's build out a line of stationary units. This will prevent our demolisher from running into the enemy base.
        # Instead they will stay at the perfect distance to attack the front two rows of the enemy base.
        for x in range(27, 5, -1):
            game_state.attempt_spawn(cheapest_unit, [x, 11])

        # Now spawn demolishers next to the line
        # By asking attempt_spawn to spawn 1000 units, it will essentially spawn as many as we have resources for
        game_state.attempt_spawn(DEMOLISHER, [24, 10], 1000)

    def least_damage_spawn_location(self, game_state, location_options):
        """
        This function will help us guess which location is the safest to spawn moving units from.
        It gets the path the unit will take then checks locations on that path to 
        estimate the path's damage risk.
        """
        damages = []
        # Get the damage estimate each path will take
        for location in location_options:
            path = game_state.find_path_to_edge(location)
            damage = 0
            for path_location in path:
                # Get number of enemy turrets that can attack each location and multiply by turret damage
                damage += len(game_state.get_attackers(path_location, 0)) * gamelib.GameUnit(TURRET, game_state.config).damage_i
            damages.append(damage)
        
        # Now just return the location that takes the least damage
        return location_options[damages.index(min(damages))]

    def detect_enemy_unit(self, game_state, unit_type=None, valid_x = None, valid_y = None):
        total_units = 0
        for location in game_state.game_map:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    if unit.player_index == 1 and (unit_type is None or unit.unit_type == unit_type) and (valid_x is None or location[0] in valid_x) and (valid_y is None or location[1] in valid_y):
                        total_units += 1
        return total_units
        
    def filter_blocked_locations(self, locations, game_state):
        filtered = []
        for location in locations:
            if not game_state.contains_stationary_unit(location):
                filtered.append(location)
        return filtered

    def on_action_frame(self, turn_string):
        """
        This is the action frame of the game. This function could be called 
        hundreds of times per turn and could slow the algo down so avoid putting slow code here.
        Processing the action frames is complicated so we only suggest it if you have time and experience.
        Full doc on format of a game frame at: https://docs.c1games.com/json-docs.html
        """
        # Let's record at what position we get scored on
        state = json.loads(turn_string)
        events = state["events"]
        breaches = events["breach"]
        for breach in breaches:
            location = breach[0]
            unit_owner_self = True if breach[4] == 1 else False
            # When parsing the frame data directly, 
            # 1 is integer for yourself, 2 is opponent (StarterKit code uses 0, 1 as player_index instead)
            if not unit_owner_self:
                gamelib.debug_write("Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)
                gamelib.debug_write("All locations: {}".format(self.scored_on_locations))


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
