"""
Functions for generating boutiques descriptors from AFNI help
"""
import argparse
from itertools import chain
import json
from pathlib import Path
import re
import boutiques.creator as bc

ALPHANUM = re.compile("[\W_]+")
FINDARGS = re.compile("ARGS=\((.*) ?\)")
FINDHELP = re.compile("\s*(-[\s\w]*)[=:}][\s\S]")


def gen_outdir(outdir):
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
    outdir = Path(outdir).resolve()
    outdir.mkdir(exist_ok=True)

    return outdir


def get_complete_args(fname):
    """
    Grabs parsed arguments for a given AFNI command in `fname`

    The file at `fname` should be a parsed AFNI command file generated by
    running `apsearch -update_all_afni_help`

    Parameters
    ----------
    fname : str
        Path to "XXXXX.complete.bash" file describing parsed AFNI command

    Returns
    -------
    args : list of str
        Putative arguments for command defined by `fname`
    """
    fpath = Path(fname).expanduser()
    if not fpath.exists():
        raise FileNotFoundError('{} does not seem to exist?'.format(fname))

    args = FINDARGS.findall(fpath.read_text())
    try:
        args = args[0].strip().replace('\'', '').split(' ')
    except IndexError:
        raise IndexError('Unable to find arguments for {}'.format(fname))

    return args


def get_usage_string(fname):
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
    text_list = fname.read_text().splitlines()
    usage_text = [val for val in text_list if
                  val.lower().strip().startswith('usage')]
    if usage_text:
        return usage_text[0]
    else:
        return None


def get_usage_params(fname):
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
    usage_text = get_usage_string(Path(fname))
    if usage_text:
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
    else:
        args = []
    return args


def get_help_fname(help_dir, cmd):
    """
    Gets most recently generated helptext for AFNI `cmd` in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    cmd : str
        AFNI command to grab help file for

    Returns
    -------
    help_fname : str
        Path to help file
    """
    help_dir = Path(help_dir).resolve()
    help_fnames = sorted(help_dir.glob(cmd + '.????_??_??-??_??_??.help'))
    try:
        return help_fnames[-1]
    except IndexError:
        raise FileNotFoundError('Cannot find any valid help files for {} in {}'
                                .format(cmd, help_dir.as_posix()))


def get_basic_help(fname, putative=None):
    """
    Gets command arguments and line number in help text for command in `fname`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command
    putative : list of str
        List of putative argument for a given AFNI command

    Returns
    -------
    params : list of dict
        Where each entry has keys ['param', 'line_start', 'length'] detailing
        the parameter name ('param'), the first line of its description in
        `helptext` ('line_start'), and putative length of its description in
        line numbers
    helptext : str
        Full helptext of tool in `fname`
    """
    helptext = Path(fname).read_text(errors='ignore').splitlines()
    params = []
    # grab parameters and line starts
    currchar = 0
    for n, f in enumerate(helptext):
        if FINDHELP.match(f) is None:
            currchar += len(f) + 1
            continue
        param = FINDHELP.findall(f)[0].strip().split(' ')[0]
        if ALPHANUM.sub('', param) == '':
            currchar += len(f) + 1
            continue
        begin = currchar + f.find(param)
        params += [dict(param=param, line_start=n, length=None,
                        param_range=[begin, begin + len(param)])]
        currchar += len(f) + 1

    # compare to list of putative arguments
    if putative is not None:
        missing = list(set(putative) - set([p.get('param') for p in params]))
        for miss in missing:
            if ALPHANUM.sub('', miss) == '':
                continue
            currchar = 0
            for n, f in enumerate(helptext):
                starts = [p.get('line_start') for p in params]
                if f.strip().startswith(miss) and n not in starts:
                    begin = currchar + f.find(miss)
                    params += [dict(param=miss, line_start=n, length=None,
                                    param_range=[begin, begin + len(miss)])]
                currchar += len(f) + 1

    # sort by line start in preparation for calculating lengths of descriptions
    params = sorted(params, key=lambda x: x.get('line_start'))

    # update potential lengths of help text
    for n, f in enumerate(params[:-1]):
        params[n]['length'] = (params[n + 1].get('line_start') -
                               f.get('line_start'))

    return params, helptext


def get_full_help(fname, putative=None):
    """
    Gets arguments and argument descriptions for command help text in `fname`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command
    putative : list of str
        List of putative argument for a given AFNI command

    Returns
    -------
    params : list of dict
        Where each entry has keys ['param', 'line_start', 'length',
        'description'] detailing the parameter name ('param'), the first line
        of its description in `helptext` ('line_start'), the putative length of
        its description in line numbers, and an attempt at parsing that
        description from `helptext` ('description')
    helptext : str
        Full helptext of tool in `fname`
    """
    params, helptext = get_basic_help(fname, putative=putative)
    fullhelp = '\n'.join(helptext)
    # iterate through parameters and get approximate description for each
    for param in params:
        ls, ln = param.get('line_start'), param.get('length')
        if ln is None:
            ln = len(helptext) + 1 - ls
        lines = helptext[ls:ls + ln]
        for n, f in enumerate(lines):
            stripped = f.lstrip()
            match = FINDHELP.match(stripped)
            if match is not None:
                lines[n] = stripped[match.end():]
                break
        param_descrip = '\n'.join(lines).rstrip()
        param['help'] = param_descrip
        ind = fullhelp.find(param_descrip)
        if ind == -1:
            ind = param['param_range'][0]
        param['help_range'] = [ind, ind + len(param_descrip)]

    return params, helptext


def gen_help_jsons(help_dir, outdir='to_boutify'):
    """
    Generates individual JSON files for each AFNI command in `help_dir`

    Output JSON files contain:
        1. Entire helptext for command, split into lines
        2. List of putative parameters for command, including starting line in
           help text and length of description

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str
        Path to where output JSON files should be saved

    Returns
    -------
    jsons : list of str
        Paths to saved JSON files
    """
    outdir = gen_outdir(outdir)
    help_dir = Path(help_dir).resolve()

    jsons = []
    # iterate through tools and get help information
    for tool in help_dir.glob('*.complete.bash'):
        tool_name = tool.name.replace('.complete.bash', '')
        params, helptext = get_full_help(get_help_fname(help_dir, tool_name),
                                         putative=get_complete_args(tool))
        jsons.append(outdir.joinpath('{}.json'.format(tool_name)).as_posix())
        with open(jsons[-1], 'w') as dest:  # save to ugly json
            json.dump(dict(helptext=helptext, params=params), dest)

    return jsons


def gen_boutique_descriptors(help_dir, outdir='afni_boutiques'):
    """
    Writes boutiques descriptors to `outdir` for AFNI help in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str
        Path to directory where generated boutiques descriptors should be saved

    Returns
    -------
    descriptors : list
        List of paths to generated boutiques descriptor JSON files
    """
    outdir = gen_outdir(outdir)
    help_dir = Path(help_dir).resolve()

    programs = [tool.name.replace('.complete.bash', '') for tool in
                help_dir.glob('*.complete.bash')]
    descriptors = []
    for cmd in programs:
        help_fname = get_help_fname(help_dir, cmd)
        params = get_full_help(help_fname)[0]
        params += [{'param': f} for f in get_usage_params(help_fname)]
        out_fname = outdir.joinpath('{}.json'.format(cmd))
        parser = argparse.ArgumentParser(add_help=False)
        for param in params:
            arg = param.get('param')
            previous = [f.option_strings for f in parser._actions] + [['']]
            # ensure argument not already in parser (and not invalid / empty)
            if arg not in list(chain.from_iterable(previous)):
                kwargs = {'required': True} if arg == '-input' else {}
                kwargs.update({'dest': '[{}]'.format(arg.strip('-').upper())}
                              if arg.startswith('-') else {})
                desc = param.get('description', 'NA')
                if desc != 'NA':
                    desc = ' '.join([f.strip() for f in desc.split('\n')])
                parser.add_argument(arg, type=str, help=desc, **kwargs)
        bout = bc.CreateDescriptor(parser, execname=cmd)
        bout.save(out_fname)
        descriptors.append(out_fname.as_posix())

    return descriptors