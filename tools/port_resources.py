# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
"""Repeatable local resource port from the user's original 1.20 mod JAR.

Original resources: Additional Blocks: Vertical Edition 1.0.3-b by CiFru,
All rights reserved. This script does not change the original archive or
fabric.mod.json, Java sources, mixin configuration, or access wideners.

References:
https://www.minecraft.net/en-us/article/minecraft-java-edition-1-21
https://www.minecraft.net/en-us/article/minecraft-java-edition-1-20-5
Fabric Resource Conditions API 4.3.0+8dc279b119 source codecs.
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_JAR = Path(r"inputs/original.jar")
RENAMES = {
    "advancements": "advancement", "recipes": "recipe",
    "loot_tables": "loot_table", "predicates": "predicate",
    "item_modifiers": "item_modifier", "functions": "function",
    "structures": "structure",
}
TAG_RENAMES = {
    "blocks": "block", "items": "item", "functions": "function",
    "entity_types": "entity_type", "fluids": "fluid",
    "game_events": "game_event",
}


def migrated_path(name):
    parts = list(PurePosixPath(name).parts)
    if parts[0] == "data" and len(parts) >= 3:
        parts[2] = RENAMES.get(parts[2], parts[2])
        if parts[2] == "tags" and len(parts) >= 4:
            parts[3] = TAG_RENAMES.get(parts[3], parts[3])
    return Path(*parts)


def material_types(source):
    code = source.read_text(encoding="utf-8")
    regular = set(re.findall(r'= createBlockType\("([^\"]+)"', code))
    optional = set(re.findall(
        r'= createBlockTypeForOtherMod\("abstoneedition", "([^\"]+)"', code))
    if not regular or not optional:
        raise ValueError("Cannot identify regular and optional material IDs in VerticalBlockType.java")
    return regular, optional


def optional_definitions(source):
    code = source.read_text(encoding="utf-8")
    pattern = (r'= createBlockTypeForOtherMod\("([^\"]+)", "([^\"]+)", "([^\"]+)", '
               r'"([^\"]+)", "([^\"]+)", "([^\"]+)", (true|false),')
    definitions = []
    for mod, material, name, slab, stair, ingredient, stonecutting in re.findall(pattern, code):
        namespace = lambda value: value if ":" in value else mod + ":" + value
        definitions.append({"mod": mod, "material": material, "name": name,
                            "slab_parent": namespace(slab), "stair_parent": namespace(stair),
                            "ingredient": namespace(ingredient), "stonecutting": stonecutting == "true"})
    if len(definitions) != len(material_types(source)[1]):
        raise ValueError("Not all optional material recipe/parent definitions were parsed")
    return definitions


def guards(definition, output):
    return [
        {"condition": "fabric:all_mods_loaded", "values": [definition["mod"]]},
        {"condition": "fabric:registry_contains", "registry": "minecraft:block", "values": [output]},
        {"condition": "fabric:registry_contains", "registry": "minecraft:item",
         "values": [definition["ingredient"], output]},
    ]


def generate_optional(args, changes):
    """Mirror VerticalRecipeProvider counts/patterns and inherit parent mining tags.

    The original TagsProvider only consulted vanilla resources. Mod parent
    blocks therefore never entered its tag sets. Read the installed companion's
    original mining tags in addition to vanilla to restore this intended link.
    """
    generated = []
    definitions = optional_definitions(args.source)
    optional_ids = block_ids({definition["material"] for definition in definitions})
    if not args.companion_resources.is_dir():
        raise ValueError("Companion resources are needed to inherit optional parent mining tags")

    def save(relative, resource):
        output = (json.dumps(resource, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        destination = args.resources / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output)
        generated.append({"target": relative.as_posix(), "ported_sha256": hashlib.sha256(output).hexdigest()})

    for definition in definitions:
        for shape, count, pattern, cut_count in (("slab", 6, ["X", "X", "X"], 2),
                                               ("stair", 4, ["XXX", " XX", "  X"], 1)):
            output = "abverticaledition:" + definition["material"] + "_vertical_" + shape
            condition = guards(definition, output)
            variants = [(output.split(":", 1)[1], {
                "type": "minecraft:crafting_shaped", "category": "building",
                "key": {"X": {"item": definition["ingredient"]}}, "pattern": pattern,
                "result": {"count": count, "id": output}, "show_notification": True,
                "fabric:load_conditions": condition,
            })]
            if definition["stonecutting"]:
                variants.append((output.split(":", 1)[1] + "_stonecutting", {
                    "type": "minecraft:stonecutting", "ingredient": {"item": definition["ingredient"]},
                    "result": {"id": output, "count": cut_count}, "fabric:load_conditions": condition,
                }))
            for recipe_name, recipe in variants:
                save(Path("data/abverticaledition/recipe") / (recipe_name + ".json"), recipe)
                recipe_id = "abverticaledition:" + recipe_name
                advancement = {
                    "parent": "minecraft:recipes/root", "fabric:load_conditions": condition,
                    "criteria": {
                        "has_item": {"trigger": "minecraft:inventory_changed",
                                     "conditions": {"items": [{"items": [definition["ingredient"]]}]}},
                        "has_the_recipe": {"trigger": "minecraft:recipe_unlocked",
                                           "conditions": {"recipe": recipe_id}},
                    },
                    "requirements": [["has_item", "has_the_recipe"]],
                    "rewards": {"recipes": [recipe_id]}, "sends_telemetry_event": False,
                }
                save(Path("data/abverticaledition/advancement/recipes/building_blocks") /
                     (recipe_name + ".json"), advancement)
                changes["generated_optional_recipes"] += 1
                changes["generated_optional_advancements"] += 1

    vanilla_files = {}
    with zipfile.ZipFile(args.vanilla_jar) as vanilla:
        for name in vanilla.namelist():
            if name.startswith("data/") and "/tags/block/" in name and name.endswith(".json"):
                vanilla_files[name] = json.loads(vanilla.read(name))
    cache = {}

    def tag_members(identifier, visiting=frozenset()):
        if identifier in cache:
            return cache[identifier]
        if identifier in visiting:
            raise ValueError("Circular parent block tag: " + identifier)
        namespace, name = identifier.split(":", 1)
        relative = Path("data") / namespace / "tags/block" / (name + ".json")
        resources = []
        vanilla = vanilla_files.get(relative.as_posix())
        if vanilla:
            resources.append(vanilla)
        companion_file = args.companion_resources / relative
        if companion_file.is_file():
            resources.append(json.loads(companion_file.read_text(encoding="utf-8")))
        members = set()
        for resource in resources:
            if resource.get("replace", False):
                members.clear()
            for entry in resource.get("values", []):
                ref = entry if isinstance(entry, str) else entry["id"]
                if ref.startswith("#"):
                    members.update(tag_members(ref[1:], visiting | {identifier}))
                else:
                    members.add(ref)
        cache[identifier] = members
        return members

    for tag in ("mineable/axe", "mineable/hoe", "mineable/pickaxe", "mineable/shovel",
                "needs_diamond_tool", "needs_iron_tool", "needs_stone_tool"):
        parents = tag_members("minecraft:" + tag)
        additions = []
        for definition in definitions:
            for shape in ("slab", "stair"):
                if definition[shape + "_parent"] in parents:
                    additions.append({"id": "abverticaledition:" + definition["material"] +
                                      "_vertical_" + shape, "required": False})
        if additions:
            relative = Path("data/minecraft/tags/block") / (tag + ".json")
            destination = args.resources / relative
            resource = json.loads(destination.read_text(encoding="utf-8")) if destination.is_file() else {"replace": False, "values": []}
            # Newly generated tag files may remain from a previous migration.
            # Replace only this script's optional entries to keep reruns stable.
            resource["values"] = [entry for entry in resource["values"]
                                  if (entry if isinstance(entry, str) else entry.get("id")) not in optional_ids]
            resource["values"].extend(additions)
            save(relative, resource)
            changes["generated_optional_tag_entries"] += len(additions)
    return generated


def block_ids(materials):
    return {"abverticaledition:" + name + suffix for name in materials
            for suffix in ("_vertical_slab", "_vertical_stair")}


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def migrate(args):
    regular, optional = material_types(args.source)
    optional_ids = block_ids(optional)
    counts = collections.Counter()
    changed = collections.Counter()
    manifest = []
    with zipfile.ZipFile(args.jar) as archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or not (name.startswith(("assets/", "data/")) or
                                     name in ("abverticaledition.png", "pack.mcmeta")):
                continue
            original = archive.read(info)
            target = migrated_path(name)
            output = original
            counts[name.split("/")[0]] += 1
            if name.startswith("data/") and name.endswith(".json"):
                resource = json.loads(original)
                if target.parts[2] == "recipe":
                    result = resource["result"]
                    if isinstance(result, str):
                        resource["result"] = {"id": result, "count": resource.pop("count", 1)}
                        changed["stonecutting_result_to_stack"] += 1
                    elif "item" in result:
                        result["id"] = result.pop("item")
                        changed["crafting_result_item_to_id"] += 1
                if target.parts[2] == "loot_table":
                    resource_id = "abverticaledition:" + target.stem
                    if resource_id in optional_ids:
                        resource["fabric:load_conditions"] = [
                            {"condition": "fabric:all_mods_loaded", "values": ["abstoneedition"]},
                            {"condition": "fabric:registry_contains", "registry": "minecraft:block",
                             "values": [resource_id]},
                            {"condition": "fabric:registry_contains", "registry": "minecraft:item",
                             "values": [resource_id]},
                        ]
                        changed["optional_loot_guard"] += 1
                output = (json.dumps(resource, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            elif name == "pack.mcmeta":
                resource = json.loads(original)
                # The mod JAR contains both client resources (34) and server data (48).
                resource["pack"]["pack_format"] = 34
                resource["pack"]["supported_formats"] = {"min_inclusive": 34, "max_inclusive": 48}
                output = (json.dumps(resource, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
                changed["pack_metadata"] += 1
            if str(target).replace("\\", "/") != name:
                changed["singular_directory"] += 1
            destination = args.resources / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(output)
            manifest.append({"source": name, "target": target.as_posix(),
                             "original_sha256": hashlib.sha256(original).hexdigest(),
                             "ported_sha256": hashlib.sha256(output).hexdigest()})
    generated = generate_optional(args, changed)
    for entry in manifest:
        entry["ported_sha256"] = hashlib.sha256((args.resources / entry["target"]).read_bytes()).hexdigest()
    report = {
        "original_jar": str(args.jar.resolve()),
        "original_jar_sha256": hashlib.sha256(args.jar.read_bytes()).hexdigest(),
        "resources": str(args.resources.resolve()),
        "minecraft": "1.21.1", "author": "CiFru", "license": "All rights reserved",
        "counts": dict(counts), "changed": dict(changed),
        "regular_material_types": len(regular), "optional_material_types": len(optional),
        "manifest": manifest,
        "generated": generated,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "changed", "regular_material_types",
                                            "optional_material_types")}, ensure_ascii=False))


def check(args):
    regular, optional = material_types(args.source)
    regular_ids, optional_ids = block_ids(regular), block_ids(optional)
    known_ids = regular_ids | optional_ids
    errors = []
    counts = collections.Counter()
    attributes = collections.Counter()
    conditions = collections.Counter()
    recipes = set()
    advancements = []
    for path in sorted(args.resources.rglob("*.json")):
        relative = path.relative_to(args.resources)
        if relative.parts[0] not in ("assets", "data"):
            continue
        try:
            resource = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            errors.append(f"{relative}: invalid JSON: {exc}")
            continue
        counts["json"] += 1
        if relative.parts[0] == "assets":
            counts["assets"] += 1
            for value in walk(resource):
                if isinstance(value, dict):
                    for key in ("parent", "model"):
                        model = value.get(key, "")
                        if isinstance(model, str) and model.startswith("abverticaledition:"):
                            ref = args.resources / "assets/abverticaledition/models" / (model.split(":", 1)[1] + ".json")
                            if not ref.is_file():
                                errors.append(f"{relative}: missing local {key} {model}")
            continue
        category = relative.parts[2]
        counts[category] += 1
        if category in RENAMES:
            errors.append(f"{relative}: old plural data directory")
        if category == "tags" and relative.parts[3] in TAG_RENAMES:
            errors.append(f"{relative}: old plural tag directory")
        if category == "recipe":
            recipe_id = relative.parts[1] + ":" + Path(*relative.parts[3:]).with_suffix("").as_posix()
            recipes.add(recipe_id)
            result = resource.get("result", {})
            if not isinstance(result, dict) or "id" not in result or "item" in result or "count" in resource:
                errors.append(f"{relative}: outdated result item stack")
            elif result["id"] not in known_ids:
                errors.append(f"{relative}: unknown mod result {result['id']}")
        if category == "advancement":
            advancements.append((relative, resource))
        if category == "tags":
            for entry in resource.get("values", []):
                ref = entry if isinstance(entry, str) else entry.get("id", "")
                if ref.startswith("abverticaledition:") and ref not in regular_ids:
                    if isinstance(entry, str) or entry.get("required", True):
                        errors.append(f"{relative}: missing or unguarded optional tag entry {ref}")
        if category == "loot_table":
            resource_id = "abverticaledition:" + path.stem
            if resource_id in optional_ids:
                guards = resource.get("fabric:load_conditions", [])
                required = {("minecraft:block", resource_id), ("minecraft:item", resource_id)}
                actual = {(g.get("registry"), value) for g in guards
                          if g.get("condition") == "fabric:registry_contains" for value in g.get("values", [])}
                if not required.issubset(actual):
                    errors.append(f"{relative}: optional loot is not guarded against missing registry entries")
                counts["conditional_loot"] += 1
            for value in walk(resource):
                if isinstance(value, dict):
                    if value.get("type") == "minecraft:item" and value.get("name") not in known_ids:
                        errors.append(f"{relative}: unknown loot item {value.get('name')}")
                    if value.get("condition") == "minecraft:block_state_property":
                        if value.get("properties") != {"state": "full"}:
                            errors.append(f"{relative}: unexpected double slab state predicate")
                    if "attribute" in value:
                        attributes[str(value["attribute"])] += 1
                    if "condition" in value:
                        conditions[str(value["condition"])] += 1
    for relative, resource in advancements:
        for recipe in resource.get("rewards", {}).get("recipes", []):
            if recipe not in recipes:
                errors.append(f"{relative}: missing rewarded recipe {recipe}")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    for entry in report["manifest"] + report.get("generated", []):
        path = args.resources / entry["target"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["ported_sha256"]:
            errors.append(f"{entry['target']}: resource differs from the migration manifest")
    print(json.dumps({"counts": dict(counts), "attributes": dict(attributes),
                      "loot_conditions": dict(conditions), "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate", "check"))
    parser.add_argument("--jar", type=Path, default=DEFAULT_JAR)
    parser.add_argument("--resources", type=Path, default=PROJECT / "output/resources")
    parser.add_argument("--source", type=Path,
                        default=PROJECT / "inputs/VerticalBlockType.java")
    parser.add_argument("--report", type=Path, default=PROJECT / "output/resource-port-report.json")
    parser.add_argument("--vanilla-jar", type=Path,
                        default=Path(r"inputs/minecraft-client.jar"))
    parser.add_argument("--companion-resources", type=Path,
                        default=PROJECT / "inputs/stone-resources")
    args = parser.parse_args()
    (migrate if args.command == "migrate" else check)(args)


if __name__ == "__main__":
    main()
