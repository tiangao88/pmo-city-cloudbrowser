#!/usr/bin/env python3
"""Create a scoped state backup without inferring installation identity."""

from common import copy_tree, parser


if __name__ == "__main__":
    args = parser(__doc__).parse_args()
    copy_tree(args)
    print(f"backup complete for instance {args.instance_id}")
