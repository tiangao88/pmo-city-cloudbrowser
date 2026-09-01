#!/usr/bin/env python3
"""Restore state from a scoped backup after an operator-selected rollback."""

from common import copy_tree, parser


if __name__ == "__main__":
    args = parser(__doc__).parse_args()
    copy_tree(args)
    print(f"rollback complete for instance {args.instance_id}")
