"""
Functions for parsing AFNI help files and generating `boutiques`-relevant JSONs
"""
import argparse
from itertools import chain
import json
from pathlib import Path
import re
import boutiques.creator as bc
import numpy as np

ALPHANUM = re.compile("[\W_]+")
FINDHELP = re.compile("\s*[\[]?(-[\s\w]*)[\s\w]*[\]=:}][\s]*")
ENDSLASH = re.compile(".*\s*\\\$")
NONALPHA = {
    '.': '__PERIOD__',
    '@': '__AT__',
    '+': '__PLUS__',
    '-': '__HYPHEN__',
}


def _gen_outdir(outdir):
    """
    Coerces `outdir` to `pathlib.Path` and creates it, if it doesn't exist

    Parameters
    ----------
    outdir : str
        Path to desired output directory

    Returns
    -------
    outdir : pathlib.Path
        Path to desired output directory
    """
    outdir = Path(outdir).expanduser().resolve()
    outdir.mkdir(exist_ok=True)

    return outdir


def _get_parsed_args(fname):
    """
    Grabs parsed arguments for a given AFNI command in `fname`

    The file at `fname` should be a parsed AFNI command file generated by
    running `apsearch -update_all_afni_help` (i.e., "COMMAND.complete.bash")

    Parameters
    ----------
    fname : str
        Path to file describing parsed AFNI command

    Returns
    -------
    args : list of str
        Putative arguments for command in `fname`
    """
    fpath = Path(fname).expanduser()
    if not fpath.exists():
        raise FileNotFoundError('{} does not seem to exist?'.format(fname))

    args = re.findall("ARGS=\((.*) ?\)", fpath.read_text(errors='ignore'))
    try:
        args = args[0].strip().replace('\'', '').split(' ')
    except IndexError:
        raise IndexError('Unable to find arguments for {}'.format(fname))

    args = list(set([re.sub("[^0-9_a-zA-Z\-]", '', a) for a in args]))
    return args


def _get_usage_string(fname):
    """
    Attempt to read usage string for a given AFNI command in `fname`

    The file at `fname` should be a full AFNI help text file generated by
    running `apsearch -update_all_afni_help`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command

    Returns
    -------
    usage : str
        Line detailing usage for command in `fname`
    """
    text_list = fname.read_text(errors='ignore').splitlines()
    usage_text = [val for val in text_list if
                  val.lower().strip().startswith('usage')]
    if usage_text:
        return usage_text[0]
    else:
        return None


def _get_usage_params(fname):
    """
    Gets positional parameters for AFNI command in `fname` from usage string

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command

    Returns
    -------
    positional : list of str
        List of putative positional arguments for command in `fname`
    """
    usage_text = _get_usage_string(Path(fname))
    if usage_text:
        try:
            text_with_bracket_args = re.sub('\[[^\[\]]*\]', '', usage_text)
            text_without_bracket_args = text_with_bracket_args.split(':')[1]
            text_with_spaces = re.sub(
                '\s+',
                ' ',
                text_without_bracket_args).strip()
            args = []
            ignore = False
            for a in text_with_spaces.split(' ')[1:]:
                if a.startswith('~'):
                    continue
                if a.startswith('-'):
                    ignore = True
                    continue
                if ignore:
                    ignore = False
                    continue
                args += [a]
        except IndexError:
            args = []
    else:
        args = []
    return args


def get_help_file(help_dir, cmd):
    """
    Gets most recently generated helptext for AFNI `cmd` in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    cmd : str
        AFNI command for which to grab help file

    Returns
    -------
    fname : str
        Path to most recently generated help file
    """
    help_dir = Path(help_dir).resolve()
    help_fnames = sorted(help_dir.glob(cmd + '.????_??_??-??_??_??.help'))
    try:
        return help_fnames[-1]
    except IndexError:
        raise FileNotFoundError('Cannot find any valid help files for {} in {}'
                                .format(cmd, help_dir.as_posix()))


def get_args_fname(help_dir, cmd):
    """
    Gets most recently parsed parameter file from AFNI `cmd` in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    cmd : str
        AFNI command for which to grab parameter file

    Returns
    -------
    help_fname : str
        Path to parameter file
    """
    help_dir = Path(help_dir).resolve()
    help_fnames = sorted(help_dir.glob(cmd + '.complete.bash'))
    try:
        return help_fnames[0]
    except IndexError:
        raise FileNotFoundError('Cannot find any valid help files for {} in {}'
                                .format(cmd, help_dir.as_posix()))


def _get_basic_help(fname, putative=None):
    """
    Gets command arguments and line number in help text for command in `fname`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command
    putative : list of str, optional
        List of putative argument for a given AFNI command. Default: None

    Returns
    -------
    params : list of dict
        Where each entry has keys of interest including:
          'param' : str, putative parameter name
          'param_range' : list of int, character range for 'param' in helptext
    helptext : list of str
        Full helptext of command from `fname` split into lines
    """
    helptext = Path(fname).read_text(errors='ignore').splitlines()
    params = []
    currchar = 0
    for n, f in enumerate(helptext):
        # if there's no parameter or the line ends in a slash, skip
        if FINDHELP.match(f) is None or ENDSLASH.match(f) is not None:
            currchar += len(f) + 1
            continue
        # grab parameter and assert it isn't non-alphanumeric
        param = FINDHELP.findall(f)[0].strip().split(' ')[0]
        if ALPHANUM.sub('', param) == '':
            currchar += len(f) + 1
            continue
        begin = currchar + f.find(param)
        params += [dict(param=param, line_start=n, length=None,
                        param_range=[begin, begin + len(param)])]
        currchar += len(f) + 1

    # compare to list of putative parameters
    if putative is not None:
        # get missing parameters and remove non-alphanumeric ones
        missing = list(set(putative) - set([p.get('param') for p in params]))
        missing = [m for m in missing if ALPHANUM.sub('', m) != '']
        # get lines on which parameters already appear (never two per line)
        starts = [p.get('line_start') for p in params]
        currchar = 0
        for n, f in enumerate(helptext):
            # skip lines that already have a parameter or end in a slash
            if n not in starts and ENDSLASH.match(f) is None:
                for miss in missing:
                    fs = f.lstrip()
                    if fs.startswith(miss):
                        # skip if non-acceptable character after parameter
                        nextchar = re.match(miss, fs).end()
                        if nextchar < len(fs):
                            if fs[nextchar] not in [' ', '}', ':', '=']:
                                continue
                        # otherwise, add to list of parameters
                        begin = currchar + f.find(miss)
                        params += [
                            dict(param=miss, line_start=n, length=None,
                                 param_range=[begin, begin + len(miss)])
                        ]
                        break  # out of `for miss in missing`
            currchar += len(f) + 1  # account for newline character

    # sort by line start in preparation for calculating lengths of descriptions
    params = sorted(params, key=lambda x: x.get('line_start'))

    # get amount of whitespace in front of each parameter
    for n, f in enumerate(params):
        curr_line = helptext[f['line_start']]
        lead = re.match('^\s*-', curr_line)
        if lead is not None:
            params[n]['lead_ws'] = lead.end() - 1
    lead_ws = [p.get('lead_ws', 0) for p in params]

    # the likelihood of only a singly parameters having a given amount of
    # leading whitespace is _very_ low, so let's drop those parameters
    ws, wsi, wsc = np.unique(lead_ws, return_inverse=True, return_counts=True)
    keep_params = [f in np.where(wsc > 1)[0] for f in wsi]
    params = [param for param, keep in zip(params, keep_params) if keep]

    # update putative lengths of help text
    for n, f in enumerate(params[:-1]):
        params[n]['length'] = (params[n + 1].get('line_start') -
                               f.get('line_start'))

    return params, helptext


def parse_help(fname, putative=None):
    """
    Gets parameters and parameter descriptions for command found at `fname`

    Parameters
    ----------
    fname : str
        Path to full help text for a given AFNI command
    putative : list of str
        List of putative arguments for command at `fname`

    Returns
    -------
    params : list of dict
        Where each entry has keys of interest including:
          'param' : str, putative parameter name
          'param_range' : list of int, character range of 'param' in `helptext`
          'help' : str, putative description of 'param'
          'help_range' : list of int, character range of 'help' in `helptext`
    helptext : list of str
        Full helptext of command from `fname` split into lines
    """
    # try to get list of putative arguments from `CMD.complete.bash` file
    if putative is None:
        try:
            cmd = fname.name.split('.')[0]
            putative = _get_parsed_args(get_args_fname(fname.parent, cmd))
        except FileNotFoundError:
            pass

    # grab parameter information and helptext
    params, helptext = _get_basic_help(fname, putative=putative)
    fullhelp = '\n'.join(helptext)

    # iterate through parameters and get description for each
    for param in params:
        # grab relevant lines of help text
        ls, ln = param.get('line_start'), param.get('length')
        if ln is None:
            ln = len(helptext) + 1 - ls
        lines = helptext[ls:ls + ln]

        # iterate through description and remove reference to parameter
        for n, f in enumerate(lines):
            stripped = f.lstrip()
            # this is a better indicator of parameter existence
            match = FINDHELP.match(stripped)
            if match is not None or stripped.startswith(param['param']):
                end = match.end() if match is not None else len(param['param'])
                lines[n] = stripped[end:]
                break

        # assign parameter description and get character ranges of description
        param_descrip = '\n'.join(lines).rstrip()
        param['help'] = param_descrip
        ind = fullhelp.find(param_descrip)
        if ind == -1:
            ind = param['param_range'][0]
        param['help_range'] = [ind, ind + len(param_descrip)]

    return params, helptext


def gen_boutify_jsons(help_dir, outdir='boutify_afni', verbose=True):
    """
    Generates JSON files for each AFNI command in `help_dir`

    Output JSON files are intended to be used in `boutify`, and thus contain:
      'helptext' : list of str, the help text for each command split into lines
      'params' : list of dict, where each entry has keys:
        'param_range' : list of int, characater range of given paramenter
        'help_range' : list of int, character range of parameter description

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str, optional
        Path to directory where output JSON files should be saved. Default:
        'boutify_afni'
    verbose : bool, optional
        Whether to print status messages of which commands are being parsed.
        Default: True

    Returns
    -------
    jsons : list of str
        Paths to saved JSON files
    """

    def get_ranges(param):
        """ Selects only 'help_range' and 'param_range' keys from `param` """
        return dict(param_range=param['param_range'],
                    help_range=param['help_range'])

    outdir = _gen_outdir(outdir)
    help_dir = Path(help_dir).expanduser().resolve()

    jsons = []
    # iterate through tools and get help information
    for tool in help_dir.glob('*.complete.bash'):
        tool_name = tool.name.replace('.complete.bash', '')
        if verbose:
            print('Generating JSON for {}.'.format(tool_name))

        # get best guess on parameter information + helptext
        params, helptext = parse_help(get_help_file(help_dir, tool_name),
                                      putative=_get_parsed_args(tool))

        # we can't have non-(alphanum characters / underscores) in filenames!
        for non_alpha, dunder_alpha in NONALPHA.items():
            tool_name = tool_name.replace(non_alpha, dunder_alpha)

        # we only need the param_range and help_range keys for each parameter
        params = [get_ranges(p) for p in params]

        # only save out one JSON if that's all we need
        jsons.append(outdir.joinpath('{}.json'.format(tool_name)))
        with jsons[-1].open('w') as dest:
            json.dump(dict(helptext=helptext, params=params), dest,
                      indent=True)

    # write `all_programs` file so we know what's in the directory
    with outdir.joinpath('all_programs').open('w') as dest:
        json.dump([p.name for p in jsons], dest, indent=True)

    return jsons


def gen_boutique_descriptors(help_dir, outdir='afni_boutiques', verbose=True):
    """
    Generates ``boutiques`` descriptors for each AFNI command in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str, optional
        Path to directory where generated descriptors should be saved. Default:
        'afni_boutiques'
    verbose : bool, optional
        Whether to print status messages of which commands are being parsed.
        Default: True

    Returns
    -------
    descriptors : list
        List of paths to generated boutiques descriptor JSON files
    """
    outdir = _gen_outdir(outdir)
    help_dir = Path(help_dir).resolve()

    descriptors = []
    for tool in help_dir.glob('*.complete.bash'):
        tool_name = tool.name.replace('.complete.bash', '')
        if verbose:
            print('Generating JSON for {}.'.format(tool_name))
        help_fname = get_help_file(help_dir, tool_name)
        out_fname = outdir.joinpath('{}.json'.format(tool_name))

        # get hypothetical parameters (both flag and positional!)
        params = parse_help(help_fname, putative=_get_parsed_args(tool))[0]
        params += [{'param': f} for f in _get_usage_params(help_fname)]

        # construct an empty parser to hold all parameters
        parser = argparse.ArgumentParser(add_help=False)
        for param in params:
            # ensure argument not already in parser (and not invalid / empty)
            arg = param.get('param')
            previous = [f.option_strings for f in parser._actions] + [['']]

            # ensure argument not already in parser (and not invalid / empty)
            if arg not in list(chain.from_iterable(previous)):
                # get info about parameter, if we have it
                kwargs = {'required': True} if arg == '-input' else {}
                kwargs.update({'dest': '{}'.format(arg.strip('-').upper())}
                              if arg.startswith('-') else {})
                desc = param.get('help', 'NA')
                if desc != 'NA':
                    desc = ' '.join([f.strip() for f in desc.split('\n')])

                # add parameter to parser
                parser.add_argument(arg, type=str, help=desc, **kwargs)

        # save out new boutiques descriptor
        bout = bc.CreateDescriptor(parser, execname=tool_name)
        bout.save(out_fname)
        descriptors.append(out_fname.as_posix())

    return descriptors


def fix_boutify_help(boutified, descdir, outdir):
    """
    DO NOT USE THIS FUNCTION IT IS NOT UPDATED
    """
    descdir, outdir = Path(descdir), Path(outdir)

    # load in boutified annotations
    with open(boutified) as src:
        annotations = json.load(src)

    # iterate through all annnotations
    for prefix, update in annotations.items():
        # load in un-boutified JSON and boutiques descriptor for updating
        desc_fname = descdir.joinpath('{}.json'.format(prefix))
        out_fname = outdir.joinpath('{}.json'.format(
            re.sub("(_part\d+)$", '', prefix).replace('_py', '.py'))
        )
        # if we don't have both then skip this annotation, I guess
        if not desc_fname.exists() or not out_fname.exists():
            continue
        with desc_fname.open() as boutified_help:
            info = json.load(boutified_help)
        with out_fname.open() as boutiques_descriptor:
            descriptor = json.load(boutiques_descriptor)

        # pull relevant info from annotation, helptext, and boutiques desc
        update = update.get('annot')
        if update is None:
            continue
        helptext = '\n'.join(info['helptext'])
        flags = [t.get('command-line-flag') for t in descriptor['inputs']]

        # go through parameters and update help in boutiques descriptor
        remove_inputs = []
        for n, param in enumerate(info['params']):
            # if there is NO help_range provided in the annotation then this
            # means we mis-classified the parameter and it should be removed
            help_ranges = update.get('h{}'.format(n))
            if help_ranges is None:
                remove_inputs += [n]
                continue

            # get the parameter name and boutified parameter description/help
            # clean up help by:
            #   1. stripping whitespace from highlight chunks
            #   2. joining higlights chunks with a space
            #   3. splitting joined text into lines
            #   4. condensing consecutive whitespace in each line
            #   5. stripping whitespace from each line
            #   6. rejoining lines with a space
            param_name = helptext[slice(*param['param_range'])]
            param_desc = ' '.join([helptext[start:end].strip() for start, end
                                   in help_ranges]).splitlines()
            param_desc = ' '.join([re.sub("\s+", ' ', f).strip()
                                   for f in param_desc])

            # reassign parameter description to the relevant boutiques input
            descriptor_index = flags.index(param_name)
            descriptor['inputs'][descriptor_index]['description'] = param_desc

        # remove all the "bad" parameters from both the inputs and command line
        for idx in sorted(remove_inputs, reverse=True):
            removed = descriptor['inputs'].pop(idx)
            new = re.sub(removed['id'] + ' ', '', descriptor['command-line'])
            descriptor['command-line'] = new

        # write out updated descriptor information
        with out_fname.open('w') as dest:
            json.dump(descriptor, dest, indent=4, sort_keys=True)
