import argparse
from pprint import pprint, PrettyPrinter
import yaml

pprinter = PrettyPrinter(indent=4, width=60)

AREA_NAMES = set('burst emanation limit wall zone'.split())
PRIMARY_ATTRIBUTES = 'attack_subeffects buffs conditions damage instant_effect knowledge subeffects teleport'.split()
SINGLE_MODIFIERS = set('casting_time choose_effect components delayable expended knowledge instant_effect no_prebuff personal_only range spell_resistance targets'.split())
#PLURAL_MODIFIERS = set('buffs conditions'.split())
# these modifiers are factored in as part of other modifiers
NONGENERIC_MODIFIERS = set('dispellable duration ignore_warnings limit_affected noncombat_buff shapeable trigger_condition trigger_duration'.split())
# convert singular to plural for consistency
TARGETING_ATTRIBUTES = set('casting_time components personal_only range shapeable spell_resistance targets'.split() + list(AREA_NAMES))
PLURAL_MAPPINGS = {
    'antibuff': 'antibuffs',
    'buff': 'buffs',
    'condition': 'conditions',
    'subeffect': 'subeffects',
    'trigger': 'triggers',
}
NESTING_ATTRIBUTES = set('subeffects attack_subeffects')
SUBSPELL_INHERITED_ATTRIBUTES = set(list(SINGLE_MODIFIERS) + list(AREA_NAMES) + 'dispellable duration ignore_warnings'.split())

# list: 0th is spell point cost of 0th level spells, 1st is spell point cost of
# 1st level spells, etc.
# Every 3 levels, the power of a spell (the spell point cost) doubles
SPELL_POINT_COSTS = (
    5,  # arcane invocation
    10, # 1st level spell
    13, # 2nd level spell
    16, # 3rd level spell
    20, # 4th level spell
    26, # 5th level spell
    32, # 6th level spell
    40, # 7th level spell
    52, # 8th level spell
    64, # 9th level spell
)

def initialize_argument_parser():
    parser = argparse.ArgumentParser(description='Assign levels to spells')
    parser.add_argument('-s', '--spell', dest='spell_name', nargs="*",
            help='Name of specific spells')
    parser.add_argument('-a', '--abilities', dest='abilities', type=str,
                        nargs='*', help = 'if provided, process abilities instead of spells')
    parser.add_argument('-t', '--type', dest='type', type=str,
            help='type of spells to get')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
            help='generate more output')
    return vars(parser.parse_args())

def import_data(args):
    with open('modifiers.yaml', 'r') as modifiersfile:
        modifiers = yaml.load(modifiersfile)
    if args.get('abilities') is not None:
        filename = 'abilities.yaml'
    else:
        filename = 'spells.yaml'
    with open(filename, 'r') as spellsfile:
        spells = yaml.load(spellsfile)
    return {
        'modifiers': modifiers,
        'spells': spells,
    }

def enforce_plural_attributes(attributes):
    # make sure only the plural versions of the attribute names are stored
    for attribute_name in attributes:
        if attribute_name in PLURAL_MAPPINGS:
            plural_attribute_name = PLURAL_MAPPINGS[attribute_name]
            attributes[plural_attribute_name] = (attributes.pop(attribute_name),)
    return attributes

def ensure_list(string_or_list):
    if isinstance(string_or_list, basestring):
        return (string_or_list,)
    else:
        return string_or_list

class Spell:
    def __init__(self, name, attributes, all_modifiers, verbose = False):
        self.name = name
        self.attributes = enforce_plural_attributes(attributes)
        self.verbose = verbose
        self.modifiers = dict()

    @property
    def ignore_warnings(self):
        return self.attributes.get('ignore_warnings')

    @property
    def affects_multiple(self):
        for attribute_name in AREA_NAMES:
            if self.has_attribute(attribute_name):
                return True
        if self.has_attribute('targets'):
            return True
        return False

    def assert_valid_attributes(self):
        primary_attribute_count = 0
        for primary_attribute in PRIMARY_ATTRIBUTES:
            if self.has_attribute(primary_attribute) and self.get_attribute(primary_attribute) is not None:
                primary_attribute_count += 1
        if primary_attribute_count == 0:
            raise Exception("Spell {0} has no primary attributes ({1})".format(self.name, pprinter.pformat(self.attributes)))
        elif primary_attribute_count >= 2:
            raise Exception("Spell {0} has too many primary attributes ({1})".format(self.name, pprinter.pformat(self.attributes)))

    def get_attribute(self, attribute):
        try:
            return self.attributes[attribute]
        except KeyError:
            raise Exception("Spell {0} does not have attribute {1}".format(self.name, attribute))
        except TypeError as e:
            raise Exception("Spell {0} had weird error getting attribute {1}: {2}".format(
                self.name, attribute, e))

    def has_attribute(self, attribute_name):
        return attribute_name in self.attributes

    def has_nested_attribute(self, attribute_name):
        attribute_name = PLURAL_MAPPINGS.get(attribute_name, attribute_name)
        return (
            attribute_name in self.attributes
            or attribute_name in self.attributes.get('attack_subeffects', {})
            or attribute_name in self.attributes.get('subeffects', {})
        )

    def add_attribute(self, attribute_name, attribute, replace_existing=True, require_nonexisting=False):
        if replace_existing or not self.has_attribute(attribute_name):
            self.attributes[attribute_name] = attribute
        elif require_nonexisting and self.has_attribute(attribute_name):
            raise Exception("Spell {0} already has attribute {1}, but require_nonexisting is true ({2})".format(self.name, attribute_name, pprinter.pformat(self.attributes)))
        # if the attribute already exists, and both replace_exiting and
        # require_nonexisting are False, silently ignore the addition

    def add_modifier(self, modifier_name, value):
        if value is None:
            raise Exception("Spell {0} can't add modifier {1} with value of None".format(self.name, modifier_name))
        if modifier_name in self.modifiers:
            try:
                self.modifiers[modifier_name].append(value)
            except AttributeError:
                modifiers = list()
                modifiers.append(self.modifiers[modifier_name])
                modifiers.append(value)
                self.modifiers[modifier_name] = modifiers
        else:
            self.modifiers[modifier_name] = value

    def get_modifier(self, modifier_name):
        try:
            return self.modifiers[modifier_name]
        except KeyError:
            raise Exception("Spell {0} does not have modifier {1}".format(self.name, modifier_name))

    def calculate_level(self, raw = False, ignore_targeting_attributes = False):
        self.assert_valid_attributes()
        self.calculate_modifiers(all_modifiers, ignore_targeting_attributes)

        level = 0
        for modifier_name in self.modifiers:
            if ignore_targeting_attributes and modifier_name in TARGETING_ATTRIBUTES:
                continue
            try:
                level += self.get_modifier(modifier_name)
            except TypeError:
                for submodifier in self.get_modifier(modifier_name):
                    level += submodifier
        if level <= 0 and not self.ignore_warnings:
            print "Warning: Spell {0} has nonpositive raw level {1}, which is usually bad".format(self.name, level)
        if raw:
            return level
        else:
            return level - 5

    def calculate_modifiers(self, all_modifiers, ignore_targeting_attributes = False):
        self.modifiers = dict()
        for attribute_name in self.attributes:
            if ignore_targeting_attributes and attribute_name in TARGETING_ATTRIBUTES:
                continue

            attribute = self.get_attribute(attribute_name)

            # skip attributes that don't actually exist
            if attribute is None:
                continue
            # most modifiers are a single dict
            # but some have nested dicts, while others don't use dicts at all
            if attribute_name == 'subeffects':
                for subeffect in attribute:
                    self.add_modifier('subeffect', self.calculate_subeffect_modifier(subeffect, all_modifiers))
            elif attribute_name == 'attack_subeffects':
                self.add_attack_subeffects_modifiers(attribute_name, attribute, all_modifiers)
            elif attribute_name == 'triggered':
                for modifier in self.calculate_triggered_modifier(all_modifiers):
                    self.add_modifier('triggered', modifier)
            else:
                # for these attributes, we are just deciding what the total
                # modifier is, not using fancy logic to assign special modifier
                # names, so the structure is more similar
                spell_level = 0
                if attribute_name in AREA_NAMES:
                    spell_level = self.calculate_area_modifier(attribute_name, attribute, all_modifiers)
                elif attribute_name == 'damage':
                    spell_level = self.calculate_damage_modifier(attribute, all_modifiers)
                elif attribute_name == 'targets':
                    spell_level = self.calculate_targets_modifier(attribute_name, attribute, all_modifiers)
                elif attribute_name == 'buffs':
                    spell_level = self.calculate_buffs_modifier(attribute, all_modifiers)
                elif attribute_name == 'conditions':
                    spell_level = self.calculate_conditions_modifier(attribute, all_modifiers)
                elif attribute_name == 'limit_affected':
                    spell_level = self.calculate_limit_affected_modifier(attribute, all_modifiers)
                elif attribute_name == 'range':
                    spell_level = self.calculate_range_modifier(attribute, all_modifiers)
                elif attribute_name == 'antibuffs':
                    spell_level = self.calculate_antibuffs_modifier(attribute, all_modifiers)
                elif attribute_name == 'instant_effect':
                    spell_level = self.calculate_instant_effect_modifier(attribute, all_modifiers)
                elif attribute_name == 'teleport':
                    spell_level = self.calculate_teleport_modifier(attribute, all_modifiers)
                elif attribute_name == 'breakable':
                    spell_level = self.calculate_breakable_modifier(attribute, all_modifiers)
                elif attribute_name == 'misc':
                    spell_level = attribute
                elif attribute_name == 'at_will_class_feature':
                    spell_level = all_modifiers['at_will_class_feature']
                elif attribute_name in SINGLE_MODIFIERS:
                    spell_level = self.calculate_generic_modifier(attribute_name, attribute, all_modifiers)
                #elif attribute_name in PLURAL_MODIFIERS:
                    #for subattribute_name in self.get_attribute(attribute_name):
                        #spell_level += super_get(all_modifiers, {attribute_name: subattribute_name})
                elif attribute_name in NONGENERIC_MODIFIERS:
                    pass
                else:
                    raise Exception("Spell {0} has unrecognized attribute {1}".format(self.name, attribute_name))
                self.add_modifier(attribute_name, spell_level)

    def calculate_subeffect_modifier(self, subeffect, all_modifiers):
        subspell = Spell('{0}.subspell'.format(self.name), subeffect, all_modifiers)
        # propagate attributes of the base spell into the subeffects
        for attribute_name in self.attributes:
            if attribute_name in SUBSPELL_INHERITED_ATTRIBUTES:
                subspell.add_attribute(attribute_name, self.get_attribute(attribute_name), replace_existing = False)
        return max(0,subspell.calculate_level(raw = True, ignore_targeting_attributes = True))

    def calculate_damage_modifier(self, attribute, all_modifiers):
        return self.calculate_generic_modifier('damage', attribute, all_modifiers)

    def add_attack_subeffects_modifiers(self, attribute_name, attribute, all_modifiers):
        if 'success' in attribute:
            success_modifier = self.calculate_success_modifier(attribute['success'], all_modifiers)
            self.add_modifier('attack success', success_modifier)
        else:
            success_modifier = 0

        if 'noncritical_effect' in attribute:
            noncritical_effect_modifier = self.calculate_subeffect_modifier(
                attribute['noncritical_effect'], all_modifiers
            )
            if success_modifier != 0 and noncritical_effect_modifier > success_modifier + 3:
                raise Exception("Spell {0} has noncritical effect more powerful than success ({1})".format(self.name, self.attributes))
            self.add_modifier('noncritical effect', noncritical_effect_modifier)
        else:
            noncritical_effect_modifier = 0

        if 'critical_success' in attribute:
            critical_success_modifier = self.calculate_critical_success_modifier(
                attribute['critical_success'], success_modifier + noncritical_effect_modifier, all_modifiers
            )
            self.add_modifier('attack critical success', max(0, critical_success_modifier) + 1)

        if 'failure' in attribute:
            failure_modifier = self.calculate_failure_modifier(
                attribute['failure'], success_modifier, all_modifiers
            )
            self.add_modifier('attack failure', max(0, failure_modifier))

        if 'effect' in attribute:
            effect_modifier = self.calculate_subeffect_modifier(
                attribute['effect'], all_modifiers
            )
            if success_modifier != 0 and effect_modifier > success_modifier + 3:
                raise Exception("Spell {0} has effect more powerful than success ({1})".format(self.name, self.attributes))
            self.add_modifier('attack effect', effect_modifier)

    def calculate_success_modifier(self, success_effects, all_modifiers):
        modifier = sum([
            self.calculate_subeffect_modifier(success_effects, all_modifiers),
            all_modifiers['attack']['success_only']
        ])
        if modifier <= 0 and not self.ignore_warnings:
            print "Warning: Spell {0} has success subeffect with level {1}, which may be too weak".format(
                self.name, modifier)
        return max(1, modifier)

    def calculate_critical_success_modifier(self, critical_success_effects, success_modifier, all_modifiers):
        modifier = sum([
            self.calculate_subeffect_modifier(critical_success_effects, all_modifiers),
            all_modifiers['attack']['critical_success_only'],
            -success_modifier
        ])
        if modifier < -1 and not self.ignore_warnings:
            print "Warning: Spell {0} has crit success subeffect with level {1}, which may be too weak".format(
                self.name, modifier)
        elif modifier > 0 and not self.ignore_warnings:
            print "Warning: Spell {0} has crit success subeffect with level {1}, which may be too strong".format(
                self.name, modifier)
        return modifier

    def calculate_failure_modifier(self, failure_effects, success_modifier, all_modifiers):
        modifier = sum([
            self.calculate_subeffect_modifier(failure_effects, all_modifiers),
            all_modifiers['attack']['failure_only'],
            -success_modifier
        ])
        if modifier < -1 and not self.ignore_warnings:
                print "Warning: Spell {0} has failure subeffect with level {1}, which may be too weak".format(
                    self.name, modifier)
        elif modifier > 0 and not self.ignore_warnings:
            print "Warning: Spell {0} has failure subeffect with level {1}, which may be too strong".format(
                self.name, modifier)
        return modifier

    def calculate_area_modifier(self, attribute_name, attribute, all_modifiers):
        area_size, area_shape = attribute.split()
        modifier = all_modifiers['area'][area_shape][area_size]
        if not self.has_attribute('targets'):
            raise Exception("Spell {0} with area must have targets ({1})".format(self.name, self.attributes))
        targets = self.get_attribute('targets')
        # if a spell affects five targets
        if targets == 'five':
            modifier = max(3, modifier - 2)
        elif targets == 'two':
            modifier = max(2, modifier - 3)
        elif targets == 'automatically_find_one':
            modifier = max(1, modifier - 2)
        elif targets == 'enemies':
            # 'enemies' matters more for larger areas
            if area_size in ('large', 'huge', 'gargantuan', 'colossal'):
                modifier += 1
        # if the spell is shapeable
        if self.has_attribute('shapeable') and area_shape in ('line', 'wall'):
            modifier += all_modifiers['shapeable'][self.get_attribute('shapeable')]
        # knowledge spells should get cheaper areas
        if self.has_attribute('knowledge'):
            modifier = max(2, modifier - 2)
        return modifier

    def calculate_buffs_modifier(self, attribute, all_modifiers):
        modifier = all_modifiers['buffs']['base']
        if not self.has_attribute('duration'):
            raise Exception("Spell {0} with buff must have duration ({1})".format(self.name, self.attributes))
        for buff in attribute:
            try:
                buff_name = buff.keys()[0]
            except AttributeError:
                buff_name = buff

            if buff_name == 'bonuses':
                # add the modifier for each component of the bonus
                buffed_statistics = ensure_list(buff[buff_name])
                for buffed_statistic in buffed_statistics:
                    modifier += self.calculate_generic_modifier('buffs', {'bonuses': buffed_statistic}, all_modifiers)
            elif buff_name == 'awesome_point':
                buffed_statistics = ensure_list(buff[buff_name])
                for buffed_statistic in buffed_statistics:
                    modifier += self.calculate_generic_modifier('buffs', {'awesome_point': buffed_statistic}, all_modifiers)
            else:
                modifier += self.calculate_generic_modifier('buffs', buff, all_modifiers)
        if self.attributes.get('personal_only'):
            duration_type = 'personal_buff'
        elif self.attributes.get('noncombat_buff'):
            duration_type = 'noncombat_buff'
        else:
            duration_type = 'nonpersonal_buff'

        # if self.affects_multiple:
            # modifier += 1

        modifier += self.calculate_duration_modifier(self.get_attribute('duration'), all_modifiers, duration_type = duration_type)
        return modifier

    def calculate_conditions_modifier(self, attribute, all_modifiers):
        if not self.has_attribute('duration'):
            raise Exception("Spell {0} with condition must have duration ({1})".format(self.name, self.attributes))
        modifier = all_modifiers['conditions']['base']
        for condition in attribute:
            try:
                condition_name = condition.keys()[0]
            except AttributeError:
                condition_name = condition

            if condition_name == 'penalties':
                # also add the modifier for each component of the penalty
                penalized_statistics = ensure_list(condition[condition_name])
                for penalized_statistic in penalized_statistics:
                    modifier += self.calculate_generic_modifier('conditions', {'penalties': penalized_statistic}, all_modifiers)
            else:
                modifier += self.calculate_generic_modifier('conditions', condition, all_modifiers)
        modifier += self.calculate_duration_modifier(self.get_attribute('duration'), all_modifiers)
        return modifier

    def calculate_duration_modifier(self, attribute, all_modifiers, duration_type = 'normal'):
        modifier = self.calculate_generic_modifier('duration', {duration_type: attribute}, all_modifiers)
        if self.has_attribute('dispellable') and not self.get_attribute('dispellable') and not attribute == 'round':
            # long durations are penalized more, but every non-round duration
            # should have some penalty
            modifier = max(modifier + 1, modifier * 1.5)
        # knowledge spells are concentration duration for convenience
        # reasons, but they shouldn't get the full benefit since the
        # advantage is usually minimal
        if attribute == 'concentration' and self.has_attribute('knowledge'):
            modifier = min(modifier + 1, 0)
        return modifier

    def calculate_instant_effect_modifier(self, attribute, all_modifiers):
        return self.calculate_generic_modifier('instant_effect', attribute, all_modifiers)

    def calculate_limit_affected_modifier(self, attribute, all_modifiers):
        if (
                self.has_attribute('buffs')
                or (
                    self.has_attribute('subeffects')
                    and 'buffs' in self.get_attribute('subeffects')
                )
        ):
            attribute = {'buff': attribute}
        else:
            attribute = {'normal': attribute}
        return self.calculate_generic_modifier('limit_affected', attribute, all_modifiers)

    def calculate_range_modifier(self, attribute, all_modifiers):
        if self.has_attribute('buffs') or self.has_attribute('teleport'):
            return self.calculate_generic_modifier('range', {'buff': attribute}, all_modifiers)
        else:
            return self.calculate_generic_modifier('range', {'normal': attribute}, all_modifiers)

    def calculate_antibuffs_modifier(self, attribute, all_modifiers):
        try:
            modifier = self.calculate_conditions_modifier(attribute, all_modifiers)
        except:
            modifier = self.calculate_buffs_modifier(attribute, all_modifiers)
        return -modifier / 2.0

    def calculate_teleport_modifier(self, attribute, all_modifiers):
        modifier = self.calculate_range_modifier(attribute['range'], all_modifiers)
        if attribute.get('unrestricted'):
            modifier += self.calculate_generic_modifier('teleport', 'unrestricted', all_modifiers)
        else:
            modifier += self.calculate_generic_modifier('teleport', 'normal', all_modifiers)
        return modifier

    def calculate_breakable_modifier(self, attribute, all_modifiers):
        attribute = ensure_list(attribute)
        modifier = 0
        for subattribute in attribute:
            modifier += self.calculate_generic_modifier('breakable', subattribute, all_modifiers)
        return modifier

    def calculate_targets_modifier(self, attribute_name, attribute, all_modifiers):
        modifier = self.calculate_generic_modifier(attribute_name, attribute, all_modifiers)
        # if we affect a specific number of targets, this could mean two things
        # it could mean we're placing a limit on the number of targets affected
        #   within the area
        # or it could mean we're affecting five targets with a spell that would
        #   otherwise not have an area
        if attribute in ('five', 'two', 'automatically_find_one'):
            # if there is an area, the modifier is handled in calculate_area_modifier
            for area_name in AREA_NAMES:
                if self.has_attribute(area_name):
                    return 0
            return modifier
        else:
            # we need to have an area if we aren't affecting a specific number
            # of targets
            for area_name in AREA_NAMES:
                if self.has_attribute(area_name):
                    return modifier
            raise Exception(
                "Spell {0} with non-specific targets {1} must have area ({2})".format(
                    self.name, attribute, self.attributes,
                )
            )
        return modifier

    def calculate_triggered_modifier(self, all_modifiers):
        if not (self.has_attribute('trigger_condition') and self.has_attribute('triggered') and self.get_attribute('triggered')):
            raise Exception("Spell {0} with trigger must have both 'triggered: true' and 'trigger_condition' ({1})".format(self.name, self.attributes))
        modifiers = list()
        modifiers.append(self.calculate_generic_modifier('trigger_condition', self.get_attribute('trigger_condition'), all_modifiers))
        if self.has_attribute('trigger_duration'):
            modifiers.append(self.calculate_duration_modifier(self.get_attribute('trigger_duration'), all_modifiers, duration_type = 'trigger'))
        return modifiers

    def calculate_triggers_modifier(self, attribute_name, attribute, all_modifiers):
        spell_level = 0
        for trigger in attribute:
            try:
                trigger_condition = trigger['trigger_condition']
                trigger_effect = trigger['subeffect']
            except KeyError:
                raise Exception("Spell {0} has invalid trigger {1}".format(self.name, pprinter.pformat(trigger)))
            spell_level += all_modifiers['trigger_condition'][trigger_condition]
            spell_level += self.calculate_subeffect_modifier(trigger_effect, all_modifiers)
        return spell_level

    def calculate_generic_modifier(self, attribute_name, attribute, all_modifiers):
        return super_get(all_modifiers, {attribute_name: attribute})

    @classmethod
    def create_by_name(cls, spell_name, spells, all_modifiers, verbose = None):
        spell_attributes = dict()
        # assign the attributes from the spell with the given name
        for key in spells[spell_name]:
            spell_attributes[key] = spells[spell_name][key]
        # spells can inherit attributes from specific 'base' spells
        while 'base' in spell_attributes:
            # remove 'base' so we can tell if there are no more base spells left
            base_spell = spells[spell_attributes.pop('base')]
            for key in base_spell:
                if key not in spell_attributes:
                    spell_attributes[key] = base_spell[key]
        # every spell also inherits from the default spell to avoid unnecessary duplication
        default_spell = spells['default_spell']
        for key in default_spell:
            if key not in spell_attributes:
                spell_attributes[key] = default_spell[key]

        return cls(spell_name, spell_attributes, all_modifiers, verbose)

    def __str__(self):
        text =  "{0}: {1}".format(self.name, self.calculate_level())
        if self.verbose:
            text += "\n({0})".format(pprinter.pformat(self.attributes))
        return text

def super_get(nested_dict, thing):
    try:
        return nested_dict[thing]
    except TypeError:
        if len(thing.keys()) > 1:
            raise Exception("Can't super_get with dict that has more than one key: {0}".format(thing))
        key = thing.keys()[0]
        value = thing[key]
        try:
            return super_get(nested_dict[key], value)
        except KeyError:
            raise Exception("Can't find key {0} in {1}".format(key, nested_dict))
    except KeyError:
        raise Exception("Can't find key {0} in {1}".format(thing, nested_dict))

if __name__ == '__main__':
    args = initialize_argument_parser()
    data = import_data(args)
    spells = data['spells']
    all_modifiers = data['modifiers']
    if args['spell_name']:
        for spell_name in args['spell_name']:
            spell = Spell.create_by_name(spell_name, spells, all_modifiers, verbose = True)
            print spell
            pprint(spell.modifiers)
            print
    else:
        for spell_name in sorted(spells.keys()):
            if spell_name == 'default_spell':
                continue
            spell = Spell.create_by_name(spell_name, spells, all_modifiers, args['verbose'])
            if args['type'] and not spell.has_nested_attribute(args['type']):
                continue
            print spell
            if args['verbose']:
                print spell.modifiers
                print
