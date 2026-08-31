# frago Recipe Community

Public recipes for [frago](https://github.com/tsaijamey/frago).

A recipe is a runnable capability an AI agent can discover and call by name —
metadata in `recipe.md`, a script beside it, and nothing else required. This
repository is where the public ones live. The frago package itself ships **no
recipes at all**: everything a user runs is either their own, under
`~/.frago/recipes/`, or installed from here.

## Using a recipe

```bash
# Find one
frago recipe search <query>

# Install it
frago recipe install community:<recipe-name>

# Run it
frago recipe run <recipe-name> --params '{...}'

# Keep it current
frago recipe update <recipe-name>
frago recipe update --all

# Remove it
frago recipe uninstall <recipe-name>
```

Installed community recipes land in `~/.frago/community-recipes/`, one level
below the user's own `~/.frago/recipes/` in frago's lookup order — so a local
recipe of the same name always wins.

## Contributing one

The fastest path is from the machine where the recipe already works:

```bash
frago recipe publish <recipe-name>
```

That forks this repository, copies the recipe into `recipes/<name>/`, and opens
a pull request for you. To do it by hand, see [CONTRIBUTING.md](./CONTRIBUTING.md);
every submission must also satisfy [SECURITY.md](./SECURITY.md).

CI validates the metadata, the script's presence and its basic syntax on every
pull request that touches `recipes/`.

## Layout

```
recipes/
└── <recipe-name>/
    ├── recipe.md      # YAML frontmatter + documentation (required)
    ├── recipe.py      # or recipe.js / recipe.sh, per `runtime`
    └── examples/      # optional
```

Flat on purpose: a recipe's `type` (`atomic` / `workflow`) and `runtime` are
declared in its metadata, and the installer files it into the right place on
the user's machine. The directory name here carries no meaning beyond identity.

## License

AGPL-3.0-or-later, same as frago. See [LICENSE](./LICENSE).
