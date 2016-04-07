from docopt import docopt
import yaml

doc = """
Usage:
    spell_engine items [-v | --verbose] [-t | --tofile] [-a=<ability> | --ability=<ability>]
    spell_engine spells [-v | --verbose] [-t | --tofile] [-a=<ability> | --ability=<ability>]
    spell_engine (-h | --help)

Options:
    -a, --ability=<ability>  Only show information for the given ability
    -h, --help               Show this screen and exit
    -v, --verbose            Show more output
"""

# let's declare some things we know about the properties

# this is the list of all valid property names
KNOWN_ABILITY_PROPERTIES = [
    'attack subeffects',
    'area',
    'breakable',
    'buffs',
    'casting time',
    'choose effect',
    'components',
    'conditions',
    'damage',
    'dispellable',
    'duration',
    'expended',
    'instant effect',
    'knowledge',
    'limit affected',
    'misc',
    'noncombat',
    'range',
    'shapeable',
    'spell resistance',
    'subeffects',
    'targets',
    'teleport',
    'trigger',
]

# exactly one of these properties must be present in any given ability
PRIMARY_PROPERTIES = [
    'attack subeffects',
    'buffs',
    'conditions',
    'damage',
    'knowledge',
    'instant effect',
    'subeffects',
    'teleport',
]

# all of these properties must be present in every ability
REQUIRED_PROPERTIES = [
    'range',
    'targets',
]

# these properties are sometimes written in the yaml file in singular form
# they should be converted to arrays for consistency
PLURAL_KEY_MAPPINGS = {
    'buff': 'buffs',
    'condition': 'conditions',
}

# these properties have default values
DEFAULT_PROPERTY_VALUES = {
    'casting time': 'standard',
    'components': 'all',
    'dispellable': True,
    'range': 'touch',
    'spell resistance': True,
    'targets': 'one',
}


def import_yaml_file(file_name):
    with open(file_name, 'r') as yaml_file:
        data = yaml.load(yaml_file)

        # handle $ref inheritance
        for key in data:
            if '$ref' in data[key]:
                parent_name = data[key]['$ref']
                try:
                    parent = data[parent_name]
                except KeyError:
                    raise Exception(
                        "Undefined $ref to parent '{0}'".format(parent_name)
                    )
                new_thing = parent.copy()
                new_thing.update(data[key])
                del new_thing['$ref']
                data[key] = new_thing
        return data
# these modifiers are used in Ability
RAW_MODIFIERS = import_yaml_file('modifiers.yaml')


def is_close(x, y, threshold=1):
    """Test whether x is within <threshold> of y

    Args:
        x (int)
        y (int)
        threshold (int)

    Yields:
        bool
    """
    return abs(x - y) <= threshold


class Ability:
    def __init__(self, name, properties):
        self.name = name

        # meta stuff to strip from properties before processing
        self.skip_validation = properties.pop('skip validation', False)

        self.properties = dict()
        for property_name in properties:
            property_value = properties[property_name]

            # convert singular keys to plural keys
            if property_name in PLURAL_KEY_MAPPINGS:
                property_name = PLURAL_KEY_MAPPINGS[property_name]
                property_value = [property_value]

            # set the property
            self.properties[property_name] = property_value

        # set default values
        for property_name in DEFAULT_PROPERTY_VALUES:
            if (self.properties.get(property_name) is None
                    or self.properties[property_name] == [None]):
                self.properties[property_name] = \
                    DEFAULT_PROPERTY_VALUES[property_name]

        self.generate_derived_properties()
        self.validate()

    def generate_derived_properties(self):
        # generate area_size, area_shape, and area_type
        if self.area is None:
            self.area_size = None
            self.area_shape = None
            self.area_type = None
        else:
            try:
                self.area_size, self.area_shape, self.area_type = \
                    self.area.split()
            except KeyError:
                self.die("has invalid area '{0}'".format(
                    self.area
                ))

        # generate duration_type
        if self.duration is None:
            self.duration_type = None
        else:
            if self.buffs is not None:
                if self.range == 'personal':
                    self.duration_type = 'personal buff'
                elif self.noncombat:
                    self.duration_type = 'noncombat buff'
                elif self.trigger:
                    self.duration_type = 'trigger'
                else:
                    self.duration_type = 'nonpersonal buff'
            elif self.knowledge is not None:
                self.duration_type = 'personal buff'
            elif self.conditions is not None:
                self.duration_type = 'condition'
            elif self.damage is not None:
                self.duration_type = 'damage over time'
            elif self.has_subeffects:
                self.duration_type = 'subeffect'
            else:
                self.die("could not determine duration_type")

        # generate limit_affected_type
        if self.limit_affected is None:
            self.limit_affected_type = None
        else:
            if self.buffs is not None:
                self.limit_affected_type = 'buff'
            else:
                self.limit_affected_type = 'normal'

        # generate targets_type
        if self.area is not None:
            self.targets_type = 'area'
        else:
            self.targets_type = 'normal'

    def get_modifier(self, property_name):
        """Get the modifier for a given property name

        Args:
            property_name (str)

        Yields:
            int
        """
        modifier_function_name = "_{0}_modifier".format(
            property_name.replace(' ', '_')
        )
        return getattr(self, modifier_function_name)()

    @property
    def has_subeffects(self):
        return (self.attack_subeffects is not None
                or self.subeffects is not None)

    def validate(self):
        if self.skip_validation:
            return

        # make sure there are no unrecognized properties
        for property_name in self.properties:
            if property_name not in KNOWN_ABILITY_PROPERTIES:
                self.die("has unknown property '{0}'".format(
                    property_name
                ))

        # make sure that all required properties are present
        for property_name in REQUIRED_PROPERTIES:
            if property_name not in self.properties:
                self.die("must have property '{0}'".format(
                    property_name
                ))

        # make sure the ability has exactly one primary property
        primary_property_count = 0
        for property_name in PRIMARY_PROPERTIES:
            if property_name in self.properties:
                primary_property_count += 1
                break
        if not primary_property_count:
            self.die("must have a primary property")
        if primary_property_count > 1:
            self.die("must have exactly one primary property")

        # here we check a bunch of weird edge cases

        # make sure that values which are not calculated for the root level
        # of abilities with subeffects are not present there
        if self.has_subeffects:
            for property_name in ['duration', 'dispellable']:
                if (property_name in self.properties
                        and self.properties[property_name] != DEFAULT_PROPERTY_VALUES[property_name]):
                    self.warn("has property '{0}' that should only be in its subeffects".format(property_name))

        # make sure that modifiers which should be positive are
        for property_name in PRIMARY_PROPERTIES:
            if (property_name in self.properties
                    and self.get_modifier(property_name) <= 0):
                self.warn("has nonpositive property '{0}'".format(
                    property_name
                ))

        # abilities with a duration must have something to apply
        # the duration to
        if (self.duration is not None
                and (self.buffs is None
                     and self.conditions is None
                     and self.knowledge is None
                     and self.damage != 'over time')):
            self.die("has duration with no purpose")

        # abilities with targets = 'five' should not have small areas
        if (self.targets == 'five'
                and self.area is not None
                and self._area_modifier() <= 2):
            self.die("has too small of an area for targets='five'")

        # make sure that attack_subeffects has no extraneous keys
        if self.attack_subeffects is not None:
            for key in self.attack_subeffects:
                if key not in ['critical success', 'effect', 'failure',
                               'noncritical effect', 'success']:
                    self.warn("has unexpected key '{0}' in attack_subeffects".format(
                        key
                    ))

        # make sure that all of the levels of subabilities within
        # attack_subeffects make sense
        if self.attack_subeffects is not None:
            sublevels = self._calculate_attack_subability_levels()
            if 'success' in sublevels:
                level_modifier = sublevels['success'] - 3
            else:
                level_modifier = (
                    sublevels.get('effect', 0)
                    + sublevels.get('noncritical effect', 0)
                )

            # check whether the 'success' part is too low
            # after un-adding the 'effect' modifiers
            unmodified_success_modifier = (
                sublevels.get('success', 0)
                - sublevels.get('effect', 0)
                - sublevels.get('noncritical effect', 0)
                - 3
            )
            if ('success' in sublevels
                    and unmodified_success_modifier <= 0):
                self.warn("has success with nonpositive level {0}".format(
                    unmodified_success_modifier
                ))

            if ('failure' in sublevels
                    and not is_close(level_modifier - 3,
                                     sublevels['failure'])):
                self.warn("has failure with incorrect level {0} instead of {1}".format(
                    sublevels['failure'],
                    level_modifier - 3,
                ))

            if 'critical success' in sublevels and not is_close(
                    level_modifier + 9,
                    sublevels['critical success'],
            ):
                self.warn("has critical success with incorrect level {0} instead of {1}".format(
                    sublevels['critical success'],
                    level_modifier + 9,
                ))

        # make sure that dispellable abilities have a reasonable duration
        if not self.dispellable and (self.duration is None
                                     or self.duration in ('round', 'concentration')):
            self.die("is not dispellable, but has trivial duration {0}".format(self.duration))


    def die(self, message):
        raise Exception("{0} {1} (properties: {2})".format(
            self,
            message,
            self.properties
        ))

    def warn(self, message):
        print "Warning: {0} {1}".format(
            self,
            message
        )

    def level(self):
        level = 0

        # call all the calculation functions

        for property_name in self.properties:
            if self.properties[property_name] is not None:
                level += self.get_modifier(property_name)

        return level

    def spell_level(self):
        return self.level() - 4

    def explain_level(self):
        print self
        for property_name in self.properties:
            # only print non-default properties
            if not (property_name in DEFAULT_PROPERTY_VALUES
                    and self.properties[property_name] == DEFAULT_PROPERTY_VALUES[property_name]):
                print "    {0}: {1}".format(
                    property_name,
                    self.get_modifier(property_name),
                )
            # subeffects should be explained individually
            if property_name == 'attack subeffects':
                print "        {0}".format(
                    self._calculate_attack_subability_levels()
                )
            elif property_name == 'subeffects':
                for subeffect_properties in self.subeffects:
                    subability = self.create_subability(subeffect_properties)
                    print "        sub: {0}".format(
                        subability.level()
                    )
        print "total:", self.spell_level()

    def __str__(self):
        return "Ability('{0}')".format(self.name)

    def create_subability(self, properties):
        """Create a subability with the given properties

        Args:
            properties (dict)

        Yields:
            Ability
        """
        return Ability(self.name + '**subability', properties)

    def _area_modifier(self):
        modifier = RAW_MODIFIERS['area'][self.area_shape][self.area_size]

        # knowledge spells pay less for areas
        if self.knowledge is not None:
            return modifier / 2.0
        else:
            return modifier

    def _attack_subeffects_modifier(self, show_warnings=True):

        # first, get the levels of all possible subabilities
        # we'll calculate the total level modifier using all of them
        sublevels = self._calculate_attack_subability_levels()

        # now that we have all the sublevels, determine the base level
        level_modifier = None
        # normally we determine the base level modifier from 'success'
        if 'success' in sublevels:
            level_modifier = sublevels['success'] - 3
        else:
            level_modifier = (
                sublevels.get('effect', 0)
                + sublevels.get('noncritical effect', 0)
            )

        # TODO: remove this!
        # this only exists for compatibility checking
        # in the new system, critical success should not cost
        # a level
        if 'critical success' in sublevels:
            level_modifier += 1

        return level_modifier

    def _calculate_attack_subability_levels(self):
        sublevels = dict()

        for modifier_name in ['critical success', 'effect', 'failure',
                              'noncritical effect', 'success']:
            if modifier_name in self.attack_subeffects:
                subability = self.create_subability(
                    self.attack_subeffects[modifier_name]
                )
                sublevels[modifier_name] = subability.level()

        # adjust the sublevels to include shared effects
        if 'effect' in sublevels:
            if 'success' in sublevels:
                sublevels['success'] += sublevels['effect']
            if 'failure' in sublevels:
                sublevels['failure'] += sublevels['effect']
            if 'critical success' in sublevels:
                sublevels['critical success'] += sublevels['effect']

        if 'noncritical effect' in sublevels:
            if 'success' in sublevels:
                sublevels['success'] += sublevels['noncritical effect']
            if 'failure' in sublevels:
                sublevels['failure'] += sublevels['noncritical effect']

        return sublevels


    def _breakable_modifier(self):
        return RAW_MODIFIERS['breakable'][self.breakable]

    def _buffs_modifier(self):
        modifier = 0

        for buff in self.buffs:
            try:
                modifier += RAW_MODIFIERS['buffs'][buff]
            except TypeError:
                # the buff is a nested modifier
                top_level_name = buff.keys()[0]
                value = buff[top_level_name]
                modifier += RAW_MODIFIERS['buffs'][top_level_name][value]

        return modifier

    def _casting_time_modifier(self):
        return RAW_MODIFIERS['casting time'][self.casting_time]

    def _conditions_modifier(self):
        modifier = 0
        for condition in self.conditions:
            modifier += RAW_MODIFIERS['conditions'][condition]
        return modifier

    def _choose_effect_modifier(self):
        return RAW_MODIFIERS['choose effect'][self.choose_effect]

    def _components_modifier(self):
        return RAW_MODIFIERS['components'][self.components]

    def _damage_modifier(self):
        try:
            return RAW_MODIFIERS['damage'][self.damage]
        except TypeError:
            # the damage is a nested modifier
            top_level_name = self.damage.keys()[0]
            value = self.damage[top_level_name]
            return RAW_MODIFIERS['damage'][top_level_name][value]

    def _dispellable_modifier(self):
        if self.dispellable:
            return 0
        elif self.duration is None:
            return 0
        else:
            return 1 + self._duration_modifier() * 0.5

    def _duration_modifier(self):
        # if the duration only exists to be passed on to
        # subeffects, don't record a duration modifier here
        if self.duration_type == 'subeffect':
            return 0
        else:
            return RAW_MODIFIERS['duration'][self.duration_type][self.duration]

    def _expended_modifier(self):
        return RAW_MODIFIERS['expended'][self.expended]

    def _instant_effect_modifier(self):
        return RAW_MODIFIERS['instant effect'][self.instant_effect]

    def _knowledge_modifier(self):
        return RAW_MODIFIERS['knowledge'][self.knowledge]

    def _limit_affected_modifier(self):
        modifiers = RAW_MODIFIERS['limit affected']
        return modifiers[self.limit_affected_type][self.limit_affected]

    def _misc_modifier(self):
        return self.misc

    def _noncombat_modifier(self):
        # being noncombat has no direct effect on an ability's level
        # but some other calculations use it
        return 0

    def _range_modifier(self):
        if self.buffs is not None:
            return RAW_MODIFIERS['range']['buff'][self.range]
        else:
            return RAW_MODIFIERS['range']['normal'][self.range]

    def _shapeable_modifier(self):
        return RAW_MODIFIERS['shapeable'][self.shapeable]

    def _spell_resistance_modifier(self):
        return RAW_MODIFIERS['spell resistance'][self.spell_resistance]

    def _subeffects_modifier(self):
        modifier = 0
        for subeffect_properties in self.subeffects:
            subability = self.create_subability(subeffect_properties)
            modifier += subability.level()
        return modifier

    def _targets_modifier(self):
        if self.targets == 'automatically find one':
            if self.targets_type == 'area':
                # reduce the area cost by half
                return - self._area_modifier() / 2
            else:
                # double the range modifier
                return self._range_modifier()
        elif self.targets == 'enemies' and self.targets_type == 'area':
            # 'enemies' matters more for larger areas
            if self._area_modifier() >= 5:
                return 2
            else:
                return 1
        else:
            return RAW_MODIFIERS['targets'][self.targets_type][self.targets]

    def _teleport_modifier(self):
        modifier = 0
        modifier += RAW_MODIFIERS['teleport']['range'][
            self.teleport['range']
        ]
        modifier += RAW_MODIFIERS['teleport']['type'][
            self.teleport['type']
        ]
        return modifier

    def _trigger_modifier(self):
        modifier = 0
        modifier += RAW_MODIFIERS['trigger']['condition'][
            self.trigger['condition']
        ]
        modifier += RAW_MODIFIERS['trigger']['duration'][
            self.trigger['duration']
        ]
        return modifier


# here we do some witchcraft to automatically add properties to Ability
# we do this because I'm too lazy to type all the @property boilerplate
def create_ability_property(property_name):
    def get_property(ability):
        return ability.properties.get(property_name, None)
    python_property_name = property_name.replace(' ', '_')
    setattr(Ability, python_property_name, property(get_property))
for property_name in KNOWN_ABILITY_PROPERTIES:
    create_ability_property(property_name)


def calculate_ability_levels(data):
    ability_levels = dict()
    for ability_name in data:
        ability = Ability(ability_name, data[ability_name])
        ability_levels[ability_name] = ability.spell_level()
    return ability_levels


def explain_ability_levels(data):
    for ability_name in data:
        ability = Ability(ability_name, data[ability_name])
        ability.explain_level()


def main(args):
    if args['items']:
        data = import_yaml_file('magic_items.yaml')
    elif args['spells']:
        data = import_yaml_file('spells.yaml')
    else:
        raise Exception("I don't know what data to use")

    if args['--ability']:
        data = {
            args['--ability']: data[args['--ability']]
        }
        args['--verbose'] = True

    if args['--verbose']:
        explain_ability_levels(data)
    elif args['--tofile']:
        with open('levels.yaml', 'w') as levels_file:
            ability_levels = calculate_ability_levels(data)
            for ability_name in sorted(ability_levels.keys()):
                levels_file.write("{}: {}\n".format(
                    ability_name,
                    ability_levels[ability_name]
                ))
    else:
        ability_levels = calculate_ability_levels(data)
        for ability_name in sorted(ability_levels.keys()):
            print "{}: {}".format(
                ability_name,
                ability_levels[ability_name]
            )

if __name__ == "__main__":
    main(docopt(doc))
