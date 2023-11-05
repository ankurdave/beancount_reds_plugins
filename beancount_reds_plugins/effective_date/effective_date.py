"""Beancount plugin to implement per-posting effective dates. See README.md for more."""

from ast import literal_eval
import copy
import datetime
import time
import string
import random
from beancount.core import data
from beancount_reds_plugins.common import common

DEBUG = 0

__plugins__ = ['effective_date']
# to enable the older transaction-level hacky plugin, now renamed to effective_date_transaction
# __plugins__ = ['effective_date', 'effective_date_transaction']

LINK_FORMAT = 'edate-{date}-{random}'


EFFECTIVE_DATE_KEY = 'date'

def has_valid_effective_date(posting):
    return posting.meta is not None and \
             EFFECTIVE_DATE_KEY in posting.meta and \
             type(posting.meta[EFFECTIVE_DATE_KEY]) == datetime.date


def has_posting_with_valid_effective_date(entry):
    for posting in entry.postings:
        if has_valid_effective_date(posting) and posting.meta[EFFECTIVE_DATE_KEY] != entry.date:
            return True
    return False


def create_new_effective_date_entry(entry, date, hold_posting, original_posting):
    def cleaned(p):
        clean_meta = copy.deepcopy(p.meta)
        clean_meta.pop(EFFECTIVE_DATE_KEY, None)
        return p._replace(meta=clean_meta)

    new_meta = {'original_date': entry.date}
    effective_date_entry = entry._replace(date=date, meta={**entry.meta, **new_meta},
                                          postings=[cleaned(hold_posting), cleaned(original_posting)])
    return effective_date_entry


def effective_date(entries, options_map):
    """Effective dates

    Args:
      entries: a list of entry instances
      options_map: a dict of options parsed from the file
      config: A configuration string, which is intended to be a Python dict
        mapping match-accounts to a pair of (negative-account, position-account)
        account names.
    Returns:
      A tuple of entries and errors.

    """
    start_time = time.time()
    errors = []

    interesting_entries = []
    filtered_entries = []
    new_accounts = set()
    for entry in entries:
        if isinstance(entry, data.Transaction) and has_posting_with_valid_effective_date(entry):
            interesting_entries.append(entry)
        else:
            filtered_entries.append(entry)

    # if DEBUG:
    #     print("------")
    #     for e in interesting_entries:
    #         printer.print_entry(e)
    #     print("------")

    # add a link to each effective date entry. this gets copied over to the newly created effective date
    # entries, and thus links each set of effective date entries
    interesting_entries_linked = []
    for entry in interesting_entries:
        rand_string = ''.join(random.choice(string.ascii_lowercase) for i in range(3))
        link = LINK_FORMAT.format(date=str(entry.date), random=rand_string)
        new_entry = entry._replace(links=(entry.links or set()) | set([link]))
        interesting_entries_linked.append(new_entry)

    new_entries = []
    for entry in interesting_entries_linked:
        modified_entry_postings = []
        for posting in entry.postings:
            if not has_valid_effective_date(posting):
                modified_entry_postings += [posting]
            else:
                holding_account = 'Assets:Hold'

                # Replace posting in original entry with holding account
                new_posting = posting._replace(account=holding_account + ':' + posting.account)
                new_accounts.add(new_posting.account)
                modified_entry_postings.append(new_posting)

                # Create new entry at effective_date
                hold_posting = new_posting._replace(units=-posting.units)
                new_entry = create_new_effective_date_entry(entry, posting.meta[EFFECTIVE_DATE_KEY],
                                                            hold_posting, posting)
                new_entries.append(new_entry)
        modified_entry = entry._replace(postings=modified_entry_postings)
        new_entries.append(modified_entry)

    # if DEBUG:
    #     print("Output results:")
    #     for e in new_entries:
    #         printer.print_entry(e)

    if DEBUG:
        elapsed_time = time.time() - start_time
        print("effective_date [{:.1f}s]: {} entries inserted.".format(elapsed_time, len(new_entries)))

    new_open_entries = common.create_open_directives(new_accounts, entries, meta_desc='<effective_date>')
    retval = new_open_entries + new_entries + filtered_entries
    return retval, errors


# TODO
# -----------------------------------------------------------------------------------------------------------
# Bug:
# below will fail because expense account was opened too late in the source:
# 2014-01-01 open Expenses:Taxes:Federal
#
# 2014-02-01 * "Estimated taxes for 2013"
# Liabilities:Mastercard    -2000 USD
# Expenses:Taxes:Federal  2000 USD
#   effective_date: 2013-12-31
