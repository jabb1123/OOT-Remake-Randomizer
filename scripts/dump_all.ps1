$rom = "C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2\The Legend of Zelda Ocarina of Time   U2.0.0.nup"
Get-ChildItem .\tmp\flows -Filter *.bfevfl.zs | ForEach-Object {
    python .\scripts\decomp_and_parse.py --rom $rom --zsdic C:\Users\jabb1123\Desktop\Roms\oot_randomizer\ZsDic.pack --out tmp/Events --dot --e_name $_.Name
}